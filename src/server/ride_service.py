"""Ride orchestration service for the HTTP backend.

This module intentionally avoids web framework and hardware dependencies. The
first backend version uses fake grid movement so the frontend/API loop can be
integrated before real car execution.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

from src.server.point_codec import coord_to_point, point_to_coord
from src.server.runtime_state import (
    RIDE_STATUS_ARRIVED,
    RIDE_STATUS_CANCELED,
    RIDE_STATUS_FAILED,
    RuntimeState,
    RuntimeStateError,
)
from src.server.schemas import RideCreateRequest, RideStatusResponse


RIDE_STATUS_TO_PICKUP = "to_pickup"
RIDE_STATUS_ARRIVED_PICKUP = "arrived_pickup"
RIDE_STATUS_IN_TRIP = "in_trip"

MAIL_STATUS_DISABLED = "disabled"
MAIL_STATUS_SENT = "sent"
MAIL_STATUS_FAILED = "failed"


class RideService:
    """编排叫车行程状态和第一版假导航。

    参数说明：
    state: RuntimeState 实例，保存小车状态、行程、消息和邮件状态。
    send_mail_fn: 可选邮件发送函数，签名为 (subject, body)。
    sleep_fn: 等待函数，假导航延迟使用；默认 time.sleep。
    """

    def __init__(
        self,
        state: RuntimeState,
        send_mail_fn: Optional[Callable[[str, str], None]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.state = state
        self.send_mail_fn = send_mail_fn
        self._sleep = sleep_fn

    def submit_ride(self, request: RideCreateRequest) -> RideStatusResponse:
        """创建行程并生成假导航路线，不立即执行完整行程。

        参数说明：
        request: 已通过 RideCreateRequest 校验的叫车请求。

        分步逻辑：
        1. 读取当前可信小车位置。
        2. 创建活动行程并生成展示路线。
        3. 记录收到叫车请求的行程消息。
        """
        car_status = self.state.get_car_status()
        ride = self.state.create_ride(request)
        route = build_fake_route(
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

    def run_fake_ride(self, ride_id: str, step_delay_seconds: float = 0.0):
        """按假路线逐点推进一个活动行程。

        参数说明：
        ride_id: submit_ride() 返回的行程 ID。
        step_delay_seconds: 每个点位之间的模拟等待时间，默认不等待。

        分步逻辑：
        1. 读取行程路线，缺失时按网格点补生成。
        2. 每个点推进前后都确认行程仍是活动行程。
        3. 按到起点、行驶中、到终点分别更新状态和消息。
        """
        try:
            ride = self.state.get_ride(ride_id)
            if not self._is_active_ride(ride_id):
                return ride

            route = ride.route or build_fake_route(
                ride.current_position,
                [ride.start, *ride.waypoints, ride.end],
            )
            if not route:
                raise RuntimeStateError(
                    "empty_route",
                    "行程路线不能为空",
                    "route",
                )

            pickup_arrived = ride.status in (
                RIDE_STATUS_ARRIVED_PICKUP,
                RIDE_STATUS_IN_TRIP,
            )
            if ride.current_position == ride.start and not pickup_arrived:
                self._mark_pickup_arrived(ride_id, ride.start, [ride.start])
                pickup_arrived = True

            for index, point in enumerate(route[1:], start=1):
                if not self._is_active_ride(ride_id):
                    return self.state.get_ride(ride_id)

                if step_delay_seconds > 0:
                    self._sleep(step_delay_seconds)
                    if not self._is_active_ride(ride_id):
                        return self.state.get_ride(ride_id)

                progress = route[: index + 1]
                if point == ride.start and not pickup_arrived:
                    self._mark_pickup_arrived(ride_id, ride.start, progress)
                    pickup_arrived = True
                    continue

                if point == ride.end and index == len(route) - 1:
                    return self._finish_arrived(ride_id, ride.end, progress)

                status = RIDE_STATUS_IN_TRIP if pickup_arrived else RIDE_STATUS_TO_PICKUP
                message = f"当前位置 {point}"
                self.state.update_ride(
                    ride_id,
                    status=status,
                    current_position=point,
                    progress=progress,
                    eta_text=message,
                )
                self.state.append_ride_event(ride_id, "car", message)

            return self.state.get_ride(ride_id)
        except Exception as exc:
            if not self._is_active_ride(ride_id):
                return self.state.get_ride(ride_id)
            return self._mark_failed(ride_id, exc)

    def cancel_ride(self, ride_id: str, reason: str = "passenger_cancel"):
        """取消活动行程并停止后续假导航推进。

        参数说明：
        ride_id: 活动行程 ID。
        reason: 取消原因，当前只记录在错误说明中。

        分步逻辑：
        1. 确认要取消的是当前活动行程。
        2. 将行程标记为 canceled 并记录取消消息。
        """
        active_ride = self.state.get_active_ride()
        if active_ride is None or active_ride.id != ride_id:
            raise RuntimeStateError(
                "ride_not_active",
                "只能取消当前活动行程",
                "ride_id",
            )

        message = "行程已取消，小车已停车"
        ride = self.state.finish_ride(
            ride_id,
            status=RIDE_STATUS_CANCELED,
            current_position=active_ride.current_position,
            eta_text=message,
            error_message=reason,
        )
        self.state.append_ride_event(ride_id, "system", message)
        return ride

    def _mark_pickup_arrived(self, ride_id: str, pickup: str, progress: List[str]):
        message = f"已到达起点 {pickup}，请上车"
        self.state.update_ride(
            ride_id,
            status=RIDE_STATUS_ARRIVED_PICKUP,
            current_position=pickup,
            progress=progress,
            eta_text=message,
        )
        self.state.append_ride_event(ride_id, "car", message)

    def _finish_arrived(self, ride_id: str, destination: str, progress: List[str]):
        message = f"已到达终点 {destination}，即将发送到达邮件"
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
        self.state.append_ride_event(ride_id, "car", message)
        self._record_arrival_mail(ride_id)
        return self.state.get_ride(ride_id)

    def _record_arrival_mail(self, ride_id: str):
        ride = self.state.get_ride(ride_id)
        route_label = " → ".join([ride.start, *ride.waypoints, ride.end])
        subject = f"4WD 小车到达通知：{ride.end}"
        body = f"小车已完成路线 {route_label}，当前位置 {ride.end}。"

        if self.send_mail_fn is None:
            self.state.record_latest_mail(
                status=MAIL_STATUS_DISABLED,
                subject=subject,
                body=body,
                error_message=None,
            )
            self.state.update_ride(ride_id, mail_status=MAIL_STATUS_DISABLED)
            self.state.append_ride_event(ride_id, "mail", "邮件发送未启用")
            return

        try:
            self.send_mail_fn(subject, body)
        except Exception as exc:
            self.state.record_latest_mail(
                status=MAIL_STATUS_FAILED,
                subject=subject,
                body=body,
                error_message=str(exc),
            )
            self.state.update_ride(ride_id, mail_status=MAIL_STATUS_FAILED)
            self.state.append_ride_event(
                ride_id,
                "mail",
                f"到达邮件发送失败：{exc}",
            )
            return

        self.state.record_latest_mail(
            status=MAIL_STATUS_SENT,
            subject=subject,
            body=body,
            error_message=None,
        )
        self.state.update_ride(ride_id, mail_status=MAIL_STATUS_SENT)
        self.state.append_ride_event(ride_id, "mail", "到达邮件已发送")

    def _mark_failed(self, ride_id: str, exc: Exception):
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
        active_ride = self.state.get_active_ride()
        return active_ride is not None and active_ride.id == ride_id


def build_fake_route(current_position: str, stops: List[str]):
    """生成前端同款曼哈顿假路线。

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
