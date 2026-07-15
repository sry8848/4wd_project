"""Ride orchestration service for the HTTP backend.

This module intentionally avoids web framework and GPIO dependencies. It
orchestrates an injected GridNavigator and records trusted-node progress.
"""

from __future__ import annotations

import logging
from threading import Condition, RLock
from typing import List

from src.server.face_verification_store import FaceVerificationStoreError
from src.server.obstacle_store import (
    HANDLING_BLOCKED_AND_REPLANNED,
    HANDLING_CANCELED_AFTER_RECOVERY,
    HANDLING_CONTINUED_CURRENT_EDGE,
    HANDLING_RECOVERY_FAILED,
    RECOVERED,
    RECOVERY_FAILED,
)
from src.server.point_codec import coord_to_point, point_to_coord
from src.server.runtime_state import (
    RIDE_STATUS_ARRIVED,
    RIDE_STATUS_AWAITING_BOARDING_CONFIRMATION,
    RIDE_STATUS_CANCELING,
    RIDE_STATUS_CANCELED,
    RIDE_STATUS_CLASSIFYING_OBSTACLE,
    RIDE_STATUS_FAILED,
    RIDE_STATUS_IN_TRIP,
    RIDE_STATUS_SCANNING_TOLL_QR,
    RIDE_STATUS_TO_PICKUP,
    RIDE_STATUS_VERIFYING_PASSENGER,
    RIDE_STATUS_WAITING_PASSENGER_RETRY,
    RIDE_STATUS_WAITING_TOLL_CLEARANCE,
    RuntimeState,
    RuntimeStateError,
)
from src.server.schemas import RideCreateRequest, RideStatusResponse
from src.tasks.edge_follow import EDGE_RECOVERED_TO_START_NODE
from src.tasks.face_verification import FACE_CANCELED, FACE_MATCHED, FACE_TIMEOUT
from src.tasks.grid_navigation import (
    NAV_ARRIVED,
    NAV_CANCELED,
    NAV_FAILED,
    NAV_NO_PATH,
    OBSTACLE_ACTION_BLOCK_AND_RECOVER,
    OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE,
    ObstacleDecision,
)
from src.tasks.obstacle_visual_classification import (
    CLASSIFICATION_SUCCESS,
    ERROR_CAMERA_UNAVAILABLE,
    ERROR_CANCELED,
    ERROR_COLOR_CONFLICT,
    ERROR_COLOR_DETECTION,
    ERROR_COLOR_TIMEOUT,
    ERROR_QR_DETECTION,
    ERROR_QR_INVALID_PAYLOAD,
    ERROR_QR_TIMEOUT,
    OBSTACLE_TYPE_TOLL,
    VISUAL_PHASE_SCANNING_TOLL_QR,
)
from src.tasks.toll_clearance import (
    CLEARANCE_CANCELED,
    CLEARANCE_CLEARED,
    CLEARANCE_ERROR,
    CLEARANCE_TIMEOUT,
)


COMMAND_RETRY_FACE = "retry_face"
COMMAND_CONFIRM_BOARDING = "confirm_boarding"
STATIONARY_PICKUP_STATUSES = (
    RIDE_STATUS_VERIFYING_PASSENGER,
    RIDE_STATUS_WAITING_PASSENGER_RETRY,
    RIDE_STATUS_AWAITING_BOARDING_CONFIRMATION,
)
OBSTACLE_PROCESSING_STATUSES = (
    RIDE_STATUS_CLASSIFYING_OBSTACLE,
    RIDE_STATUS_SCANNING_TOLL_QR,
    RIDE_STATUS_WAITING_TOLL_CLEARANCE,
)
VISUAL_FAILURE_MESSAGES = {
    ERROR_COLOR_TIMEOUT: "未在时限内确认障碍颜色，正在倒回并重新规划",
    ERROR_COLOR_CONFLICT: "同时检测到红色和蓝色，正在倒回并重新规划",
    ERROR_COLOR_DETECTION: "颜色识别异常，正在倒回并重新规划",
    ERROR_CAMERA_UNAVAILABLE: "摄像头读取失败，正在倒回并重新规划",
    ERROR_QR_TIMEOUT: "收费站二维码识别超时，正在倒回并重新规划",
    ERROR_QR_INVALID_PAYLOAD: "收费站二维码内容无效，正在倒回并重新规划",
    ERROR_QR_DETECTION: "收费站二维码识别异常，正在倒回并重新规划",
}
TOLL_CLEARANCE_FAILURE_MESSAGES = {
    CLEARANCE_TIMEOUT: "等待畅通超时，正在倒回并重新规划",
    CLEARANCE_ERROR: "超声波读数异常，正在倒回并重新规划",
}

LOGGER = logging.getLogger(__name__)


class RideService:
    """编排叫车行程状态以及注入的真实导航器。

    参数说明：
    state: RuntimeState 实例，保存小车状态、行程和消息。
    mail_notifier: AsyncMailNotifier 或遵守相同 notify() 契约的测试对象。
    """

    def __init__(
        self,
        state: RuntimeState,
        mail_notifier,
    ):
        self.state = state
        self.mail_notifier = mail_notifier
        self._state_lock = RLock()
        self._command_condition = Condition(self._state_lock)
        self._cancel_reasons = {}
        self._pending_commands = {}

    def submit_ride(self, request: RideCreateRequest) -> RideStatusResponse:
        """创建真实硬件行程并生成前端展示路线。

        参数说明：
        request: 已通过 RideCreateRequest 校验的叫车请求。

        分步逻辑：
        1. 读取当前可信小车位置。
        2. 创建活动行程并生成初始展示路线。
        3. 记录收到叫车请求的行程消息。
        """
        car_status = self.state.get_car_status()
        ride = self.state.create_ride(request)
        route = build_display_route(
            car_status.current_position,
            [ride.start, *ride.waypoints, ride.end],
        )
        self.state.update_ride(
            ride.id,
            route=route,
            progress=[car_status.current_position],
            eta_text="正在前往起点",
        )
        self.state.append_ride_event(
            ride.id,
            "car",
            f"收到叫车请求，当前上报位置 {car_status.current_position}",
        )
        return self.state.get_ride(ride.id)

    def run_hardware_ride(
        self,
        ride_id: str,
        navigator,
        obstacle_recorder,
        face_verifier,
        face_recorder,
        obstacle_visual_task,
        toll_clearance_task,
    ):
        """使用已创建的 GridNavigator 执行真实分段行程。

        参数说明：
        ride_id: submit_ride() 返回的活动行程 ID。
        navigator: hardware_factory 创建的 GridNavigator；本方法不拥有或关闭它。
        obstacle_recorder: 后端摄像头帧写盘能力与 ObstacleStore 的业务组合对象。
        face_verifier: 使用后端唯一摄像头的指定乘客核验任务。
        face_recorder: 保存每次成功或超时结果的记录器。
        obstacle_visual_task: 固定摄像头颜色与收费站二维码任务。
        toll_clearance_task: 只读取超声波后台缓存的收费站畅通确认任务。

        分步逻辑：
        1. 按当前位置、起点、途径点、终点逐段调用真实导航。
        2. 每到一个可信节点就更新位置、朝向、进度和后续路线预览。
        3. 把取消、无路和硬件失败映射为对应行程终态。
        """
        try:
            ride = self.state.get_ride(ride_id)
            if not self._is_active_ride(ride_id):
                return ride

            stops = [ride.start, *ride.waypoints, ride.end]
            pickup_arrived = ride.current_position == ride.start
            if pickup_arrived:
                may_continue = self._verify_and_wait_for_boarding(
                    ride_id,
                    face_verifier,
                    face_recorder,
                )
                if not may_continue:
                    return self.state.get_ride(ride_id)

            for stop_index, stop in enumerate(stops):
                if not self._is_active_ride(ride_id):
                    return self.state.get_ride(ride_id)
                if stop_index == 0 and pickup_arrived:
                    continue

                car_status = self.state.get_car_status()
                remaining_stops = stops[stop_index:]
                segment_ride = self.state.get_ride(ride_id)
                road_status = (
                    RIDE_STATUS_IN_TRIP
                    if segment_ride.status == RIDE_STATUS_IN_TRIP
                    else RIDE_STATUS_TO_PICKUP
                )

                def report_node(node, heading):
                    with self._state_lock:
                        if not self._is_active_ride(ride_id):
                            return
                        point = coord_to_point(node)
                        current_ride = self.state.get_ride(ride_id)
                        progress = list(current_ride.progress)
                        if not progress or progress[-1] != point:
                            progress.append(point)
                        preview = build_display_route(point, remaining_stops)
                        route = [*progress, *preview[1:]]
                        if self._is_cancel_requested(ride_id):
                            status = RIDE_STATUS_CANCELING
                            message = f"已到达前方节点 {point}，正在停车"
                        else:
                            status = (
                                RIDE_STATUS_IN_TRIP
                                if current_ride.status == RIDE_STATUS_IN_TRIP
                                else RIDE_STATUS_TO_PICKUP
                            )
                            message = f"当前位置 {point}"
                        self.state.update_ride(
                            ride_id,
                            status=status,
                            current_position=point,
                            heading=heading,
                            route=route,
                            progress=progress,
                            eta_text=message,
                        )
                        self.state.append_ride_event(ride_id, "car", message)

                def set_obstacle_stage(status, message):
                    """Publish one obstacle business stage without overwriting canceling."""

                    with self._state_lock:
                        if not self._is_active_ride(ride_id):
                            return
                        if self._is_cancel_requested(ride_id) and status != RIDE_STATUS_CANCELING:
                            return
                        self.state.update_ride(
                            ride_id,
                            status=status,
                            eta_text=message,
                        )
                        self.state.append_ride_event(ride_id, "obstacle", message)

                def decide_obstacle(from_node, to_node, distance_cm):
                    """Run stopped visual classification and return one navigation action."""

                    from_point = coord_to_point(from_node)
                    to_point = coord_to_point(to_node)
                    set_obstacle_stage(
                        RIDE_STATUS_CLASSIFYING_OBSTACLE,
                        f"检测到障碍 {from_point}—{to_point}，正在识别颜色",
                    )

                    def report_visual_phase(phase):
                        if phase != VISUAL_PHASE_SCANNING_TOLL_QR:
                            raise RuntimeError(f"未知障碍视觉阶段: {phase}")
                        set_obstacle_stage(
                            RIDE_STATUS_SCANNING_TOLL_QR,
                            "已确认蓝色障碍，正在识别收费站二维码",
                        )

                    visual_result = obstacle_visual_task.classify(
                        cancel_requested_fn=lambda: (
                            not self._is_active_ride(ride_id)
                            or self._is_cancel_requested(ride_id)
                        ),
                        phase_changed_fn=report_visual_phase,
                    )
                    if visual_result.obstacle_type != OBSTACLE_TYPE_TOLL:
                        if visual_result.recognition_error == ERROR_CANCELED:
                            set_obstacle_stage(
                                RIDE_STATUS_CANCELING,
                                "已停止障碍识别，正在倒回可信节点",
                            )
                        elif visual_result.classification_status == CLASSIFICATION_SUCCESS:
                            set_obstacle_stage(
                                road_status,
                                "已确认红色普通障碍，正在倒回并重新规划",
                            )
                        else:
                            set_obstacle_stage(
                                road_status,
                                VISUAL_FAILURE_MESSAGES[
                                    visual_result.recognition_error
                                ],
                            )
                        return ObstacleDecision(
                            OBSTACLE_ACTION_BLOCK_AND_RECOVER,
                            context=visual_result,
                        )

                    set_obstacle_stage(
                        RIDE_STATUS_WAITING_TOLL_CLEARANCE,
                        f"已识别收费站 {visual_result.station_id}，即将通过收费站",
                    )
                    clearance = toll_clearance_task.wait(
                        cancel_requested_fn=lambda: (
                            not self._is_active_ride(ride_id)
                            or self._is_cancel_requested(ride_id)
                        )
                    )
                    if clearance.outcome == CLEARANCE_CLEARED:
                        set_obstacle_stage(
                            road_status,
                            f"收费站 {visual_result.station_id} 前方已确认畅通，即将通过收费站",
                        )
                        return ObstacleDecision(
                            OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE,
                            context=visual_result,
                        )

                    if clearance.outcome == CLEARANCE_CANCELED:
                        set_obstacle_stage(
                            RIDE_STATUS_CANCELING,
                            "已停止等待收费站，正在倒回可信节点",
                        )
                    else:
                        set_obstacle_stage(
                            road_status,
                            f"收费站 {visual_result.station_id} "
                            f"{TOLL_CLEARANCE_FAILURE_MESSAGES[clearance.outcome]}",
                        )
                    return ObstacleDecision(
                        OBSTACLE_ACTION_BLOCK_AND_RECOVER,
                        context=visual_result,
                    )

                def report_obstacle(
                    from_node,
                    to_node,
                    distance_cm,
                    decision,
                    handling_status,
                    _final_heading,
                ):
                    """Save the selected frame while stopped and publish the result."""

                    from_point = coord_to_point(from_node)
                    to_point = coord_to_point(to_node)
                    if handling_status == OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE:
                        handling_result = HANDLING_CONTINUED_CURRENT_EDGE
                        recovery_status = None
                        recovered_point = None
                    elif handling_status == EDGE_RECOVERED_TO_START_NODE:
                        handling_result = (
                            HANDLING_CANCELED_AFTER_RECOVERY
                            if self._is_cancel_requested(ride_id)
                            else HANDLING_BLOCKED_AND_REPLANNED
                        )
                        recovery_status = RECOVERED
                        recovered_point = from_point
                    else:
                        handling_result = HANDLING_RECOVERY_FAILED
                        recovery_status = RECOVERY_FAILED
                        recovered_point = None
                    try:
                        record = obstacle_recorder.record(
                            ride_id=ride_id,
                            from_point=from_point,
                            to_point=to_point,
                            distance_cm=distance_cm,
                            visual_result=decision.context,
                            handling_result=handling_result,
                            recovery_status=recovery_status,
                            recovered_point=recovered_point,
                        )
                    except Exception as exc:
                        LOGGER.exception(
                            "Failed to persist obstacle for ride=%s edge=%s-%s",
                            ride_id,
                            from_point,
                            to_point,
                        )
                        with self._state_lock:
                            if self._is_active_ride(ride_id):
                                self.state.append_ride_event(
                                    ride_id,
                                    "system",
                                    f"检测到障碍 {from_point}—{to_point}，但记录保存失败：{exc}",
                                )
                        return

                    status_text = {
                        HANDLING_CONTINUED_CURRENT_EDGE: "已沿当前边继续",
                        HANDLING_BLOCKED_AND_REPLANNED: "已倒回并重新规划",
                        HANDLING_CANCELED_AFTER_RECOVERY: "取消后已倒回可信节点",
                        HANDLING_RECOVERY_FAILED: "恢复失败",
                    }[record.handling_result]
                    message = (
                        f"检测到障碍 {from_point}—{to_point}，"
                        f"确认距离 {record.distance_cm:.1f} cm，"
                        f"{status_text}"
                    )
                    with self._state_lock:
                        if self._is_active_ride(ride_id):
                            self.state.append_ride_event(
                                ride_id,
                                "obstacle",
                                message,
                                obstacle_id=record.id,
                            )

                result = navigator.navigate(
                    point_to_coord(car_status.current_position),
                    point_to_coord(stop),
                    car_status.heading,
                    obstacle_decision_fn=decide_obstacle,
                    cancel_requested_fn=lambda: not self._is_active_ride(ride_id),
                    node_reached_fn=report_node,
                    stop_at_next_node_fn=lambda: self._is_cancel_requested(ride_id),
                    obstacle_result_fn=report_obstacle,
                )
                with self._state_lock:
                    if self._is_cancel_requested(ride_id):
                        return self._finish_canceled_at_node(ride_id)
                    if result == NAV_CANCELED:
                        return self.state.get_ride(ride_id)
                    if result == NAV_NO_PATH:
                        raise RuntimeError(f"无法规划到点位 {stop} 的路线")
                    if result == NAV_FAILED:
                        raise RuntimeError(f"导航到点位 {stop} 时硬件执行失败")
                    if result != NAV_ARRIVED:
                        raise RuntimeError(f"未知导航结果: {result}")

                    current_ride = self.state.get_ride(ride_id)
                    progress = list(current_ride.progress)

                if stop_index == 0:
                    may_continue = self._verify_and_wait_for_boarding(
                        ride_id,
                        face_verifier,
                        face_recorder,
                    )
                    if not may_continue:
                        return self.state.get_ride(ride_id)
                elif stop == ride.end:
                    return self._finish_arrived(ride_id, ride.end, progress)
                else:
                    self._mark_waypoint_arrived(ride_id, stop, progress)

            return self.state.get_ride(ride_id)
        except Exception as exc:
            with self._state_lock:
                if not self._is_active_ride(ride_id):
                    return self.state.get_ride(ride_id)
                return self._mark_failed(ride_id, exc)

    def request_cancel_ride(self, ride_id: str, reason: str = "passenger_cancel"):
        """请求活动行程在前方下一个可信节点停车。

        参数说明：
        ride_id: 活动行程 ID。
        reason: 取消原因，当前只记录在错误说明中。

        分步逻辑：
        1. 确认要取消的是当前活动行程。
        2. 保持行程活动，将状态标记为 canceling。
        3. 当前边继续执行，由 GridNavigator 到达前方节点后完成取消。
        """
        with self._command_condition:
            active_ride = self.state.get_active_ride()
            if active_ride is None or active_ride.id != ride_id:
                raise RuntimeStateError(
                    "ride_not_active",
                    "只能取消当前活动行程",
                    "ride_id",
                )

            if ride_id in self._cancel_reasons:
                return active_ride

            if active_ride.status in STATIONARY_PICKUP_STATUSES:
                self._pending_commands.pop(ride_id, None)
                canceled = self.state.finish_ride(
                    ride_id,
                    status=RIDE_STATUS_CANCELED,
                    current_position=active_ride.current_position,
                    eta_text="行程已取消，小车保持在起点停车",
                    error_message=reason,
                )
                self.state.append_ride_event(ride_id, "system", canceled.eta_text)
                self._command_condition.notify_all()
                return canceled

            self._cancel_reasons[ride_id] = reason
            if active_ride.status in OBSTACLE_PROCESSING_STATUSES:
                message = "取消请求已收到，小车将停止识别并倒回可信节点"
            else:
                message = "取消请求已收到，小车将在前方下一个节点停车"
            ride = self.state.update_ride(
                ride_id,
                status=RIDE_STATUS_CANCELING,
                eta_text=message,
            )
            self.state.append_ride_event(ride_id, "system", message)
            return ride

    def request_face_verification_retry(self, ride_id: str):
        """在同一活动行程中提交一次人脸重新识别命令。"""

        with self._command_condition:
            ride = self._require_active_status(
                ride_id,
                RIDE_STATUS_WAITING_PASSENGER_RETRY,
                "当前行程不在等待重新识别状态",
            )
            if ride_id in self._pending_commands:
                raise RuntimeStateError(
                    "ride_command_pending",
                    "当前行程已有待处理命令",
                    "ride_id",
                )
            self._pending_commands[ride_id] = COMMAND_RETRY_FACE
            message = "已请求重新识别乘客"
            updated = self.state.update_ride(
                ride_id,
                status=RIDE_STATUS_VERIFYING_PASSENGER,
                eta_text=message,
            )
            self.state.append_ride_event(ride_id, "passenger", message)
            self._command_condition.notify_all()
            return updated

    def confirm_boarding(self, ride_id: str):
        """确认指定乘客已上车并唤醒原行程线程。"""

        with self._command_condition:
            self._require_active_status(
                ride_id,
                RIDE_STATUS_AWAITING_BOARDING_CONFIRMATION,
                "当前行程不在等待确认上车状态",
            )
            if ride_id in self._pending_commands:
                raise RuntimeStateError(
                    "ride_command_pending",
                    "当前行程已有待处理命令",
                    "ride_id",
                )
            self._pending_commands[ride_id] = COMMAND_CONFIRM_BOARDING
            message = "已确认上车，即将继续行程"
            updated = self.state.update_ride(
                ride_id,
                status=RIDE_STATUS_IN_TRIP,
                eta_text=message,
            )
            self.state.append_ride_event(ride_id, "passenger", message)
            self._command_condition.notify_all()
            return updated

    def force_cancel_ride(self, ride_id: str, reason: str = "server_shutdown"):
        """在服务关闭等场景立即终止行程，不等待下一个节点。

        参数说明：
        ride_id: 当前活动行程 ID。
        reason: 强制终止原因，仅用于错误说明。
        """

        with self._command_condition:
            self._cancel_reasons.pop(ride_id, None)
            self._pending_commands.pop(ride_id, None)
            ride = self.state.get_ride(ride_id)
            canceled = self.state.finish_ride(
                ride_id,
                status=RIDE_STATUS_CANCELED,
                current_position=ride.current_position,
                eta_text="服务正在关闭，小车已紧急停车",
                error_message=reason,
            )
            self.state.append_ride_event(ride_id, "system", canceled.eta_text)
            self._command_condition.notify_all()
            return canceled

    def _finish_canceled_at_node(self, ride_id: str):
        """在导航确认的前方节点完成用户取消请求。"""

        with self._state_lock:
            ride = self.state.get_ride(ride_id)
            reason = self._cancel_reasons.pop(ride_id, "passenger_cancel")
            message = f"行程已取消，小车已在节点 {ride.current_position} 停车"
            canceled = self.state.finish_ride(
                ride_id,
                status=RIDE_STATUS_CANCELED,
                current_position=ride.current_position,
                eta_text=message,
                error_message=reason,
            )
            canceled = self.state.update_ride(
                ride_id,
                route=list(canceled.progress),
            )
            self.state.append_ride_event(ride_id, "system", message)
            return canceled

    def _verify_and_wait_for_boarding(self, ride_id, face_verifier, face_recorder):
        """在起点停车后反复验脸，并等待确认上车或取消。"""

        with self._state_lock:
            if self._is_cancel_requested(ride_id):
                self._finish_canceled_at_node(ride_id)
                return False
            if not self._is_active_ride(ride_id):
                return False
            ride = self.state.get_ride(ride_id)
            event = self.state.append_ride_event(
                ride_id,
                "car",
                f"已到达起点 {ride.start}，正在核验乘客 {ride.passenger_id}",
            )
        self._queue_point_mail(ride_id, "起点", ride.start, event.created_at)

        while True:
            with self._state_lock:
                if not self._is_active_ride(ride_id):
                    return False
                message = f"正在识别乘客 {ride.passenger_id}"
                self.state.update_ride(
                    ride_id,
                    status=RIDE_STATUS_VERIFYING_PASSENGER,
                    current_position=ride.start,
                    eta_text=message,
                )
                self.state.append_ride_event(ride_id, "car", message)
            result = face_verifier.verify(
                ride.passenger_id,
                cancel_requested_fn=lambda: not self._is_active_ride(ride_id),
            )
            if result.outcome == FACE_CANCELED or not self._is_active_ride(ride_id):
                return False

            record = None
            record_error = None
            try:
                record = face_recorder.record(
                    ride_id=ride_id,
                    passenger_id=ride.passenger_id,
                    verification_result=result,
                )
            except FaceVerificationStoreError as exc:
                LOGGER.exception("Failed to persist face verification for ride=%s", ride_id)
                record_error = str(exc)

            with self._state_lock:
                if not self._is_active_ride(ride_id):
                    return False
                record_id = record.id if record is not None else None
                image_url = record.image_url if record is not None else None
                self.state.update_ride(
                    ride_id,
                    face_verification_id=record_id,
                    face_verification_image_url=image_url,
                )

                save_error = record_error or (
                    record.image_error if record is not None else None
                )
                if result.outcome == FACE_MATCHED:
                    message = f"乘客 {ride.passenger_id} 核验成功，等待确认上车"
                    if save_error is not None:
                        message += f"；识别照片保存失败：{save_error}"
                    self.state.update_ride(
                        ride_id,
                        status=RIDE_STATUS_AWAITING_BOARDING_CONFIRMATION,
                        eta_text=message,
                    )
                    self.state.append_ride_event(ride_id, "car", message)
                elif result.outcome == FACE_TIMEOUT:
                    message = "本次乘客核验超时，小车继续在起点停车"
                    if save_error is not None:
                        message += f"；诊断照片保存失败：{save_error}"
                    self.state.update_ride(
                        ride_id,
                        status=RIDE_STATUS_WAITING_PASSENGER_RETRY,
                        eta_text=message,
                    )
                    self.state.append_ride_event(ride_id, "car", message)
                else:
                    raise RuntimeError(f"未知人脸核验结果: {result.outcome}")

            if result.outcome == FACE_MATCHED:
                return self._wait_for_command(ride_id) == COMMAND_CONFIRM_BOARDING
            if self._wait_for_command(ride_id) != COMMAND_RETRY_FACE:
                return False

    def _wait_for_command(self, ride_id: str):
        """释放状态锁并无限期等待同一行程的一项用户命令。"""

        with self._command_condition:
            while self._is_active_ride(ride_id) and ride_id not in self._pending_commands:
                self._command_condition.wait()
            if not self._is_active_ride(ride_id):
                self._pending_commands.pop(ride_id, None)
                return None
            return self._pending_commands.pop(ride_id)

    def _require_active_status(self, ride_id: str, expected_status: str, message: str):
        """校验用户命令只作用于指定活动行程的准确状态。"""

        active_ride = self.state.get_active_ride()
        if active_ride is None or active_ride.id != ride_id:
            raise RuntimeStateError(
                "ride_not_active",
                "只能操作当前活动行程",
                "ride_id",
            )
        if active_ride.status != expected_status:
            raise RuntimeStateError(
                "invalid_ride_operation",
                message,
                "status",
            )
        return active_ride

    def _mark_waypoint_arrived(
        self,
        ride_id: str,
        waypoint: str,
        progress: List[str],
    ):
        """记录途径点到达并提交对应 QQ 邮件。"""

        message = f"已到达途径点 {waypoint}，继续前往下一站"
        event = self.state.append_ride_event(ride_id, "car", message)
        self.state.update_ride(
            ride_id,
            status=RIDE_STATUS_IN_TRIP,
            current_position=waypoint,
            progress=progress,
            eta_text=message,
        )
        self._queue_point_mail(
            ride_id,
            "途径点",
            waypoint,
            event.created_at,
        )

    def _finish_arrived(self, ride_id: str, destination: str, progress: List[str]):
        self._cancel_reasons.pop(ride_id, None)
        self._pending_commands.pop(ride_id, None)
        message = f"已到达终点 {destination}，行程完成"
        self.state.finish_ride(
            ride_id,
            status=RIDE_STATUS_ARRIVED,
            current_position=destination,
            eta_text=message,
        )
        self.state.update_ride(
            ride_id,
            progress=progress,
        )
        event = self.state.append_ride_event(ride_id, "car", message)
        self._queue_point_mail(
            ride_id,
            "终点",
            destination,
            event.created_at,
        )
        return self.state.get_ride(ride_id)

    def _queue_point_mail(
        self,
        ride_id: str,
        point_kind: str,
        point: str,
        arrived_at: str,
    ):
        """提交到点邮件，发送结果只写消息，不改变行程状态。"""

        ride = self.state.get_ride(ride_id)
        route_label = " → ".join([ride.start, *ride.waypoints, ride.end])
        subject = f"4WD 小车到达{point_kind}：{point}"
        body = "\n".join(
            (
                f"通知类型：到达{point_kind}",
                f"到达点位：{point}",
                f"完整路线：{route_label}",
                f"到达时间：{arrived_at}",
            )
        )

        def record_result(error):
            with self._state_lock:
                try:
                    self.state.get_ride(ride_id)
                except RuntimeStateError:
                    LOGGER.exception(
                        "Mail result references missing ride=%s",
                        ride_id,
                    )
                    return
                if error is None:
                    self.state.append_ride_event(
                        ride_id,
                        "mail",
                        f"QQ 邮件已发送：到达{point_kind} {point}",
                    )
                else:
                    self.state.append_ride_event(
                        ride_id,
                        "system",
                        f"QQ 邮件发送失败（到达{point_kind} {point}）：{error}",
                    )

        try:
            self.mail_notifier.notify(subject, body, record_result)
        except Exception as exc:
            record_result(exc)

    def _mark_failed(self, ride_id: str, exc: Exception):
        self._cancel_reasons.pop(ride_id, None)
        self._pending_commands.pop(ride_id, None)
        ride = self.state.get_ride(ride_id)
        message = f"行程失败：{exc}"
        failed = self.state.finish_ride(
            ride_id,
            status=RIDE_STATUS_FAILED,
            current_position=ride.current_position,
            eta_text=message,
            error_message=str(exc),
        )
        self.state.append_ride_event(ride_id, "system", message)
        return failed

    def _is_active_ride(self, ride_id: str):
        with self._state_lock:
            active_ride = self.state.get_active_ride()
            return active_ride is not None and active_ride.id == ride_id

    def _is_cancel_requested(self, ride_id: str):
        """返回当前活动行程是否正在等待节点停车。"""

        with self._state_lock:
            active_ride = self.state.get_active_ride()
            return (
                active_ride is not None
                and active_ride.id == ride_id
                and ride_id in self._cancel_reasons
            )


def build_display_route(current_position: str, stops: List[str]):
    """生成前端使用的曼哈顿展示路线。

    参数说明：
    current_position: 小车当前可信位置。
    stops: 行程目标点，顺序为起点、途径点、终点。

    分步逻辑：
    1. 把当前位置放到路线首位。
    2. 逐段拼接相邻目标点之间的网格路径。
    """
    route_stops = [current_position, *stops]
    route = []
    for index, stop in enumerate(route_stops[1:]):
        segment = build_grid_segment(route_stops[index], stop)
        route.extend(segment if index == 0 else segment[1:])
    return route


def build_grid_segment(start: str, end: str):
    """生成两个点之间的水平优先网格路径。

    参数说明：
    start: 起始点位，例如 C3。
    end: 结束点位，例如 A1。

    分步逻辑：
    1. 先沿列方向移动。
    2. 再沿行方向移动。
    """
    start_row, start_col = point_to_coord(start, "start")
    end_row, end_col = point_to_coord(end, "end")
    row = start_row
    col = start_col
    path = [coord_to_point((row, col))]

    while col != end_col:
        col += 1 if col < end_col else -1
        path.append(coord_to_point((row, col)))

    while row != end_row:
        row += 1 if row < end_row else -1
        path.append(coord_to_point((row, col)))

    return path
