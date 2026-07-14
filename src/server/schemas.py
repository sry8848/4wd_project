"""HTTP API request and response schemas for the ride-hailing backend."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from src.server.point_codec import (
    COLS,
    ROWS,
    PointValidationError,
    all_points,
    validate_route_stops,
)


PASSENGER_ID_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}$")


@dataclass(frozen=True)
class RideCreateRequest:
    """叫车请求数据。

    参数说明：
    passenger_id: 已登记并由用户选择的乘客标签。
    start: 乘客起点，格式为 A1 到 E5。
    waypoints: 途径点列表，第一版最多 3 个。
    end: 乘客终点，格式为 A1 到 E5。
    """

    passenger_id: str
    start: str
    waypoints: List[str]
    end: str

    @classmethod
    def from_payload(cls, payload):
        """从前端 JSON 字典创建并校验叫车请求。

        参数说明：
        payload: HTTP 请求体反序列化后的字典，只允许 passenger_id、start、waypoints、end。
        """
        if not isinstance(payload, dict):
            raise PointValidationError(
                "invalid_request",
                "请求体必须是 JSON 对象",
            )

        required_fields = ("passenger_id", "start", "waypoints", "end")
        for field in required_fields:
            if field not in payload:
                raise PointValidationError(
                    "invalid_request",
                    f"缺少请求字段: {field}",
                    field,
                )

        allowed_fields = set(required_fields)
        for field in payload:
            if field not in allowed_fields:
                raise PointValidationError(
                    "invalid_request",
                    f"不支持请求字段: {field}",
                    field,
                )

        passenger_id = payload["passenger_id"]
        if not isinstance(passenger_id, str) or not PASSENGER_ID_RE.fullmatch(
            passenger_id
        ):
            raise PointValidationError(
                "invalid_passenger",
                "passenger_id 必须是 1 到 32 位已登记乘客标签",
                "passenger_id",
            )

        start, waypoints, end = validate_route_stops(
            payload["start"],
            payload["waypoints"],
            payload["end"],
        )
        return cls(
            passenger_id=passenger_id,
            start=start,
            waypoints=waypoints,
            end=end,
        )

    def to_dict(self):
        """转换为可 JSON 序列化的字典。

        参数说明：
        无。返回值用于 HTTP 响应或测试断言。
        """
        return asdict(self)


@dataclass(frozen=True)
class GridResponse:
    """前端网格定义响应。

    参数说明：
    rows: 网格行名称。
    cols: 网格列名称。
    points: 可选点位列表。
    blocked_points: 当前不可通行点位。
    blocked_edges: 当前不可通行边。
    """

    rows: List[str]
    cols: List[str]
    points: List[str]
    blocked_points: List[str]
    blocked_edges: List[List[str]]

    @classmethod
    def default(cls):
        """创建当前 5x5 前端网格响应。

        参数说明：
        无。第一版没有默认封锁点或封锁边。
        """
        return cls(
            rows=list(ROWS),
            cols=list(COLS),
            points=all_points(),
            blocked_points=[],
            blocked_edges=[],
        )

    def to_dict(self):
        """转换为可 JSON 序列化的字典。

        参数说明：
        无。返回值用于 HTTP 响应或测试断言。
        """
        return asdict(self)


@dataclass(frozen=True)
class CarStatusResponse:
    """小车状态响应。

    参数说明：
    online: 后端是否认为小车服务在线。
    mode: 小车模式，例如 idle、running、stopping、error。
    current_position: 当前可信网格点位。
    heading: 当前朝向。
    active_ride_id: 当前活动行程 ID，没有活动行程时为 None。
    last_message: 最近一条展示消息。
    updated_at: ISO 8601 时间字符串。
    """

    online: bool
    mode: str
    current_position: str
    heading: str
    active_ride_id: Optional[str]
    last_message: str
    updated_at: str

    def to_dict(self):
        """转换为可 JSON 序列化的字典。

        参数说明：
        无。返回值用于 HTTP 响应或测试断言。
        """
        return asdict(self)


@dataclass(frozen=True)
class RideStatusResponse:
    """行程状态响应。

    参数说明：
    id: 行程 ID。
    status: 行程状态，例如 to_pickup、verifying_passenger、arrived。
    passenger_id: 本次行程必须核验的已登记乘客标签。
    start: 起点。
    waypoints: 途径点列表。
    end: 终点。
    current_position: 当前可信位置。
    route: 后端规划出的完整展示路径。
    progress: 已完成路径。
    eta_text: 前端展示用状态文字。
    error_message: 失败原因，没有失败时为 None。
    face_verification_id: 最新一次已持久化人脸核验记录 ID。
    face_verification_image_url: 最新记录存在真实 JPEG 时的读取地址。
    created_at: 创建时间。
    updated_at: 更新时间。
    """

    id: str
    status: str
    passenger_id: str
    start: str
    waypoints: List[str]
    end: str
    current_position: str
    route: List[str]
    progress: List[str]
    eta_text: str
    error_message: Optional[str]
    face_verification_id: Optional[str]
    face_verification_image_url: Optional[str]
    created_at: str
    updated_at: str

    def to_dict(self):
        """转换为可 JSON 序列化的字典。

        参数说明：
        无。返回值用于 HTTP 响应或测试断言。
        """
        return asdict(self)


@dataclass(frozen=True)
class RideEventResponse:
    """行程消息事件响应。

    参数说明：
    seq: 递增消息序号。
    type: 消息类型，例如 system、passenger、car、mail、obstacle。
    text: 消息正文。
    created_at: 消息创建时间。
    obstacle_id: 障碍消息关联的持久化记录 ID；其它消息为 None。
    """

    seq: int
    type: str
    text: str
    created_at: str
    obstacle_id: Optional[str] = None

    def to_dict(self):
        """转换为可 JSON 序列化的字典。

        参数说明：
        无。返回值用于 HTTP 响应或测试断言。
        """
        return asdict(self)


@dataclass(frozen=True)
class ObstacleRecordResponse:
    """一次已确认障碍的持久化展示记录。

    参数说明：
    id: 障碍记录 ID，同时用于读取对应图片。
    ride_id: 发现障碍的行程 ID。
    created_at: 完成恢复并保存记录的时间。
    from_point/to_point: 被阻塞的有向网格边。
    distance_cm: 连续确认障碍时最后一次有效距离。
    recovered_point: 成功恢复后的可信节点；恢复失败时为 None。
    status: recovered 或 recovery_failed。
    image_url: 真实图片接口地址；没有真实图片时为 None。
    capture_error: 抓拍失败原因；成功时为 None。
    """

    id: str
    ride_id: str
    created_at: str
    from_point: str
    to_point: str
    distance_cm: float
    recovered_point: Optional[str]
    status: str
    image_url: Optional[str]
    capture_error: Optional[str]

    def to_dict(self):
        """转换为可 JSON 序列化的字典。"""

        return asdict(self)


@dataclass(frozen=True)
class ErrorDetail:
    """接口错误详情。

    参数说明：
    code: 统一错误码。
    message: 可返回给前端展示的错误说明。
    details: 额外定位信息，例如出错字段。
    """

    code: str
    message: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class ErrorResponse:
    """统一错误响应。

    参数说明：
    error: 错误详情对象。
    """

    error: ErrorDetail

    @classmethod
    def from_validation_error(cls, error):
        """把点位或请求校验错误转换为 HTTP 错误响应体。

        参数说明：
        error: PointValidationError 实例。
        """
        details = {}
        if error.field is not None:
            details["field"] = error.field
        return cls(
            error=ErrorDetail(
                code=error.code,
                message=error.message,
                details=details,
            )
        )

    def to_dict(self):
        """转换为可 JSON 序列化的字典。

        参数说明：
        无。返回值用于 HTTP 响应或测试断言。
        """
        return {"error": asdict(self.error)}
