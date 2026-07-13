"""Ride orchestration service for the HTTP backend.

This module intentionally avoids web framework and GPIO dependencies. It
orchestrates an injected GridNavigator and records trusted-node progress.
"""

from __future__ import annotations

import logging
from threading import RLock
from typing import List

from src.server.point_codec import coord_to_point, point_to_coord
from src.server.runtime_state import (
    RIDE_STATUS_ARRIVED,
    RIDE_STATUS_CANCELING,
    RIDE_STATUS_CANCELED,
    RIDE_STATUS_FAILED,
    RuntimeState,
    RuntimeStateError,
)
from src.server.schemas import RideCreateRequest, RideStatusResponse
from src.tasks.grid_navigation import (
    NAV_ARRIVED,
    NAV_CANCELED,
    NAV_FAILED,
    NAV_NO_PATH,
)


RIDE_STATUS_TO_PICKUP = "to_pickup"
RIDE_STATUS_ARRIVED_PICKUP = "arrived_pickup"
RIDE_STATUS_IN_TRIP = "in_trip"

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
        self._cancel_reasons = {}

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
            eta_text="派单中",
        )
        self.state.append_ride_event(
            ride.id,
            "car",
            f"收到叫车请求，当前上报位置 {car_status.current_position}",
        )
        return self.state.get_ride(ride.id)

    def run_hardware_ride(self, ride_id: str, navigator, obstacle_recorder):
        """使用已创建的 GridNavigator 执行真实分段行程。

        参数说明：
        ride_id: submit_ride() 返回的活动行程 ID。
        navigator: hardware_factory 创建的 GridNavigator；本方法不拥有或关闭它。
        obstacle_recorder: 后端长期摄像头与 ObstacleStore 的业务组合对象。

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
                self._mark_pickup_arrived(
                    ride_id,
                    ride.start,
                    list(ride.progress),
                )

            for stop_index, stop in enumerate(stops):
                if not self._is_active_ride(ride_id):
                    return self.state.get_ride(ride_id)
                if stop_index == 0 and pickup_arrived:
                    continue

                car_status = self.state.get_car_status()
                remaining_stops = stops[stop_index:]

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
                                if current_ride.status
                                in (RIDE_STATUS_ARRIVED_PICKUP, RIDE_STATUS_IN_TRIP)
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

                def report_obstacle(
                    from_node,
                    to_node,
                    distance_cm,
                    recovery_status,
                    _final_heading,
                ):
                    """在节点恢复和居中完成后保存并发布障碍记录。"""

                    from_point = coord_to_point(from_node)
                    to_point = coord_to_point(to_node)
                    try:
                        record = obstacle_recorder.record(
                            ride_id=ride_id,
                            from_point=from_point,
                            to_point=to_point,
                            distance_cm=distance_cm,
                            recovery_status=recovery_status,
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

                    status_text = (
                        "已恢复并绕行"
                        if record.status == "recovered"
                        else "恢复失败"
                    )
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
                    if stop_index == 0:
                        self._mark_pickup_arrived(
                            ride_id,
                            ride.start,
                            list(current_ride.progress),
                        )
                    elif stop == ride.end:
                        return self._finish_arrived(
                            ride_id,
                            ride.end,
                            list(current_ride.progress),
                        )
                    else:
                        self._mark_waypoint_arrived(
                            ride_id,
                            stop,
                            list(current_ride.progress),
                        )

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
        with self._state_lock:
            active_ride = self.state.get_active_ride()
            if active_ride is None or active_ride.id != ride_id:
                raise RuntimeStateError(
                    "ride_not_active",
                    "只能取消当前活动行程",
                    "ride_id",
                )

            if ride_id in self._cancel_reasons:
                return active_ride

            self._cancel_reasons[ride_id] = reason
            message = "取消请求已收到，小车将在前方下一个节点停车"
            ride = self.state.update_ride(
                ride_id,
                status=RIDE_STATUS_CANCELING,
                eta_text=message,
            )
            self.state.append_ride_event(ride_id, "system", message)
            return ride

    def force_cancel_ride(self, ride_id: str, reason: str = "server_shutdown"):
        """在服务关闭等场景立即终止行程，不等待下一个节点。

        参数说明：
        ride_id: 当前活动行程 ID。
        reason: 强制终止原因，仅用于错误说明。
        """

        with self._state_lock:
            self._cancel_reasons.pop(ride_id, None)
            ride = self.state.get_ride(ride_id)
            canceled = self.state.finish_ride(
                ride_id,
                status=RIDE_STATUS_CANCELED,
                current_position=ride.current_position,
                eta_text="服务正在关闭，小车已紧急停车",
                error_message=reason,
            )
            self.state.append_ride_event(ride_id, "system", canceled.eta_text)
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

    def _mark_pickup_arrived(self, ride_id: str, pickup: str, progress: List[str]):
        with self._state_lock:
            pickup_message = f"已到达起点 {pickup}，请上车"
            is_canceling = self._is_cancel_requested(ride_id)
            status = (
                RIDE_STATUS_CANCELING
                if is_canceling
                else RIDE_STATUS_ARRIVED_PICKUP
            )
            message = (
                "取消请求已收到，小车将在前方下一个节点停车"
                if is_canceling
                else pickup_message
            )
            event = self.state.append_ride_event(
                ride_id,
                "car",
                pickup_message,
            )
            self.state.update_ride(
                ride_id,
                status=status,
                current_position=pickup,
                progress=progress,
                eta_text=message,
            )
            self._queue_point_mail(
                ride_id,
                "起点",
                pickup,
                event.created_at,
            )

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
