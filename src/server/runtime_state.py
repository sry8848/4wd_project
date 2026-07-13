"""In-memory runtime state for the HTTP backend."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from src.server.point_codec import normalize_point
from src.server.schemas import (
    CarStatusResponse,
    LatestMailResponse,
    RideCreateRequest,
    RideEventResponse,
    RideStatusResponse,
)


HEADING_NORTH = "north"
HEADING_EAST = "east"
HEADING_SOUTH = "south"
HEADING_WEST = "west"
VALID_HEADINGS = (HEADING_NORTH, HEADING_EAST, HEADING_SOUTH, HEADING_WEST)

CAR_MODE_IDLE = "idle"
CAR_MODE_RUNNING = "running"
CAR_MODE_ERROR = "error"

RIDE_STATUS_DISPATCHING = "dispatching"
RIDE_STATUS_ARRIVED = "arrived"
RIDE_STATUS_FAILED = "failed"
RIDE_STATUS_CANCELED = "canceled"
TERMINAL_RIDE_STATUSES = (
    RIDE_STATUS_ARRIVED,
    RIDE_STATUS_FAILED,
    RIDE_STATUS_CANCELED,
)


class RuntimeStateError(RuntimeError):
    """表示后端运行状态不允许当前操作。

    参数说明：
    code: 统一错误码，例如 ride_already_running。
    message: 可返回给前端展示的错误说明。
    field: 可选字段名，用于定位维护接口输入错误。
    """

    def __init__(self, code, message, field=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


class RuntimeState:
    """保存后端进程内的小车状态、活动行程、消息和邮件状态。

    参数说明：
    initial_position: 服务启动时的小车可信点位。
    initial_heading: 服务启动时的小车朝向。
    now_fn: 返回 ISO 8601 时间字符串的函数；默认使用当前 UTC 时间。
    """

    def __init__(
        self,
        initial_position="C3",
        initial_heading=HEADING_NORTH,
        now_fn: Optional[Callable[[], str]] = None,
    ):
        self._now = now_fn if now_fn is not None else _utc_now_iso
        self._current_position = normalize_point(initial_position, "initial_position")
        self._heading = _validate_heading(initial_heading)
        self._mode = CAR_MODE_IDLE
        self._active_ride_id = None
        self._last_message = "等待小车上报位置。"
        self._updated_at = self._now()
        self._ride_counter = 0
        self._rides: Dict[str, RideStatusResponse] = {}
        self._ride_events: Dict[str, List[RideEventResponse]] = {}
        self._latest_mail = LatestMailResponse(
            status="none",
            subject="暂无真实邮件",
            body="完成行程后，后端会记录最近一次到达邮件状态。",
            sent_at=None,
            error_message=None,
        )

    def get_car_status(self):
        """返回当前小车状态。

        参数说明：
        无。返回值用于 `/api/car/status`。
        """
        return CarStatusResponse(
            online=True,
            mode=self._mode,
            current_position=self._current_position,
            heading=self._heading,
            active_ride_id=self._active_ride_id,
            last_message=self._last_message,
            updated_at=self._updated_at,
        )

    def set_car_position(self, position, heading):
        """校准小车可信位置和朝向。

        参数说明：
        position: A1 到 E5 的点位。
        heading: north/east/south/west 之一。
        """
        if self._active_ride_id is not None:
            raise RuntimeStateError(
                "car_busy",
                "小车运行中，不能校准位置",
                "position",
            )

        normalized_position = normalize_point(position, "position")
        validated_heading = _validate_heading(heading)
        self._current_position = normalized_position
        self._heading = validated_heading
        self._touch(f"小车位置已校准为 {normalized_position}，朝向 {validated_heading}")
        return self.get_car_status()

    def create_ride(self, request: RideCreateRequest):
        """创建一个活动行程。

        参数说明：
        request: 已通过 RideCreateRequest 校验的叫车请求。
        """
        if self._active_ride_id is not None:
            raise RuntimeStateError(
                "ride_already_running",
                "已有活动行程，不能重复叫车",
            )

        created_at = self._now()
        self._ride_counter += 1
        ride_id = f"ride-{created_at.replace(':', '').replace('-', '')}-{self._ride_counter}"
        ride = RideStatusResponse(
            id=ride_id,
            status=RIDE_STATUS_DISPATCHING,
            start=request.start,
            waypoints=list(request.waypoints),
            end=request.end,
            current_position=self._current_position,
            route=[],
            progress=[self._current_position],
            eta_text="派单中",
            mail_status="pending",
            error_message=None,
            created_at=created_at,
            updated_at=created_at,
        )
        self._rides[ride_id] = ride
        self._ride_events[ride_id] = []
        self._active_ride_id = ride_id
        self._mode = CAR_MODE_RUNNING
        self._updated_at = created_at

        route_label = " → ".join([request.start, *request.waypoints, request.end])
        self.append_ride_event(ride_id, "passenger", f"请求路线 {route_label}")
        return self._rides[ride_id]

    def get_active_ride(self):
        """返回当前活动行程，没有活动行程时返回 None。

        参数说明：
        无。接口层可用 None 转换为 204 No Content。
        """
        if self._active_ride_id is None:
            return None
        return self._rides[self._active_ride_id]

    def get_ride(self, ride_id):
        """按 ID 返回行程。

        参数说明：
        ride_id: create_ride() 返回的行程 ID。
        """
        try:
            return self._rides[ride_id]
        except KeyError as exc:
            raise RuntimeStateError(
                "ride_not_found",
                f"行程不存在: {ride_id}",
            ) from exc

    def append_ride_event(self, ride_id, event_type, text):
        """追加一条行程消息事件。

        参数说明：
        ride_id: 行程 ID。
        event_type: system/passenger/car/mail 等消息类型。
        text: 消息正文。
        """
        self.get_ride(ride_id)
        events = self._ride_events[ride_id]
        created_at = self._now()
        event = RideEventResponse(
            seq=len(events) + 1,
            type=event_type,
            text=text,
            created_at=created_at,
        )
        events.append(event)
        self._touch(text, updated_at=created_at)
        return event

    def list_ride_events(self, ride_id, after=0) -> Tuple[List[RideEventResponse], int]:
        """查询指定序号之后的行程消息。

        参数说明：
        ride_id: 行程 ID。
        after: 只返回 seq 大于 after 的事件。
        """
        self.get_ride(ride_id)
        events = [event for event in self._ride_events[ride_id] if event.seq > after]
        next_after = self._ride_events[ride_id][-1].seq if self._ride_events[ride_id] else after
        return events, next_after

    def update_ride(
        self,
        ride_id,
        *,
        status=None,
        current_position=None,
        heading=None,
        route=None,
        progress=None,
        eta_text=None,
        mail_status=None,
        error_message=None,
    ):
        """更新非终止行程状态。

        参数说明：
        ride_id: 行程 ID。
        status: 新行程状态，不传则保持原值。
        current_position: 新可信位置，不传则保持原值。
        heading: 导航确认的新朝向，不传则保持当前小车朝向。
        route: 新完整路径，不传则保持原值。
        progress: 新进度路径，不传则保持原值。
        eta_text: 前端展示文字，不传则保持原值。
        mail_status: 邮件状态，不传则保持原值。
        error_message: 错误说明，不传则保持原值。
        """
        ride = self.get_ride(ride_id)
        updated_position = (
            normalize_point(current_position, "current_position")
            if current_position is not None
            else ride.current_position
        )
        updated_heading = (
            _validate_heading(heading) if heading is not None else self._heading
        )
        updated_at = self._now()
        updated = replace(
            ride,
            status=status if status is not None else ride.status,
            current_position=updated_position,
            route=list(route) if route is not None else ride.route,
            progress=list(progress) if progress is not None else ride.progress,
            eta_text=eta_text if eta_text is not None else ride.eta_text,
            mail_status=mail_status if mail_status is not None else ride.mail_status,
            error_message=error_message,
            updated_at=updated_at,
        )
        self._rides[ride_id] = updated
        self._current_position = updated_position
        self._heading = updated_heading
        if eta_text is not None:
            self._last_message = eta_text
        self._updated_at = updated_at
        return updated

    def finish_ride(self, ride_id, *, status, current_position, eta_text, error_message=None):
        """把行程切换为终止状态并清除活动行程。

        参数说明：
        ride_id: 行程 ID。
        status: arrived/failed/canceled 之一。
        current_position: 终止时的可信位置。
        eta_text: 前端展示文字。
        error_message: 失败或取消原因，没有时为 None。
        """
        if status not in TERMINAL_RIDE_STATUSES:
            raise RuntimeStateError(
                "invalid_ride_status",
                f"不支持的终止状态: {status}",
                "status",
            )

        ride = self.update_ride(
            ride_id,
            status=status,
            current_position=current_position,
            eta_text=eta_text,
            error_message=error_message,
        )
        if self._active_ride_id == ride_id:
            self._active_ride_id = None
        self._mode = CAR_MODE_ERROR if status == RIDE_STATUS_FAILED else CAR_MODE_IDLE
        return ride

    def get_latest_mail(self):
        """返回最近一次邮件状态。

        参数说明：
        无。返回值用于 `/api/mail/latest`。
        """
        return self._latest_mail

    def record_latest_mail(self, *, status, subject, body, error_message=None):
        """记录最近一次邮件状态。

        参数说明：
        status: none/pending/sent/failed 等邮件状态。
        subject: 邮件主题。
        body: 邮件正文摘要。
        error_message: 失败原因，没有失败时为 None。
        """
        self._latest_mail = LatestMailResponse(
            status=status,
            subject=subject,
            body=body,
            sent_at=self._now() if status == "sent" else None,
            error_message=error_message,
        )
        return self._latest_mail

    def _touch(self, message, updated_at=None):
        self._last_message = message
        self._updated_at = updated_at if updated_at is not None else self._now()


def _validate_heading(heading):
    if heading not in VALID_HEADINGS:
        raise RuntimeStateError(
            "invalid_heading",
            "heading 必须是 north/east/south/west",
            "heading",
        )
    return heading


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
