"""Point-name conversion and validation for the 5x5 frontend grid."""

import re


ROWS = ("A", "B", "C", "D", "E")
COLS = ("1", "2", "3", "4", "5")
POINT_RE = re.compile(r"^[A-E][1-5]$")
MAX_WAYPOINTS = 3


class PointValidationError(ValueError):
    """表示前端点位输入不符合后端接口契约。

    参数说明：
    code: 统一错误码，例如 invalid_point、duplicate_stop。
    message: 可直接返回给前端展示的中文错误说明。
    field: 出错字段名称，例如 start、end 或 waypoints[0]。
    """

    def __init__(self, code, message, field=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def all_points():
    """返回前端 5x5 网格的全部点位名称。

    返回值：
    按 A1 到 E5 的页面顺序返回 25 个点位字符串。
    """
    return [f"{row}{col}" for row in ROWS for col in COLS]


def normalize_point(point, field="point"):
    """校验并规范化单个点位名称。

    参数说明：
    point: 前端提交的点位，例如 A1、c3。
    field: 出错时用于定位字段的名称。
    """
    if not isinstance(point, str):
        raise PointValidationError(
            "invalid_point",
            f"{field} 必须是 A1 到 E5 之间的点位",
            field,
        )

    normalized = point.strip().upper()
    if not POINT_RE.match(normalized):
        raise PointValidationError(
            "invalid_point",
            f"{field} 必须是 A1 到 E5 之间的点位",
            field,
        )

    return normalized


def point_to_coord(point, field="point"):
    """把 A1 这类页面点位转换为零基坐标。

    参数说明：
    point: 前端展示点位，例如 A1。
    field: 出错时用于定位字段的名称。
    """
    normalized = normalize_point(point, field)
    return ROWS.index(normalized[0]), COLS.index(normalized[1:])


def coord_to_point(coord, field="coord"):
    """把零基坐标转换为 A1 这类页面点位。

    参数说明：
    coord: 二元组 (row, col)，row/col 都为零基整数。
    field: 出错时用于定位字段的名称。
    """
    if (
        not isinstance(coord, tuple)
        or len(coord) != 2
        or not isinstance(coord[0], int)
        or not isinstance(coord[1], int)
    ):
        raise PointValidationError(
            "invalid_point",
            f"{field} 必须是 (row, col) 坐标",
            field,
        )

    row, col = coord
    if row < 0 or row >= len(ROWS) or col < 0 or col >= len(COLS):
        raise PointValidationError(
            "invalid_point",
            f"{field} 超出 A1 到 E5 的网格范围",
            field,
        )

    return f"{ROWS[row]}{COLS[col]}"


def validate_route_stops(start, waypoints, end):
    """校验叫车路线中的起点、途径点和终点。

    参数说明：
    start: 起点点位。
    waypoints: 途径点列表，第一版最多 3 个。
    end: 终点点位。
    """
    if waypoints is None:
        waypoints = []
    if not isinstance(waypoints, list):
        raise PointValidationError(
            "invalid_point",
            "waypoints 必须是点位列表",
            "waypoints",
        )
    if len(waypoints) > MAX_WAYPOINTS:
        raise PointValidationError(
            "too_many_waypoints",
            f"途径点最多只能设置 {MAX_WAYPOINTS} 个",
            "waypoints",
        )

    normalized_start = normalize_point(start, "start")
    normalized_end = normalize_point(end, "end")
    normalized_waypoints = [
        normalize_point(point, f"waypoints[{index}]")
        for index, point in enumerate(waypoints)
    ]

    if normalized_start == normalized_end:
        raise PointValidationError(
            "same_start_end",
            "起点和终点不能相同",
            "end",
        )

    stops = [normalized_start, *normalized_waypoints, normalized_end]
    if len(set(stops)) != len(stops):
        raise PointValidationError(
            "duplicate_stop",
            "起点、途径点和终点不能重复",
            "waypoints",
        )

    return normalized_start, normalized_waypoints, normalized_end


def route_points_to_coords(start, waypoints, end):
    """把已校验路线点位转换为导航层使用的零基坐标。

    参数说明：
    start: 起点点位。
    waypoints: 途径点列表。
    end: 终点点位。
    """
    normalized_start, normalized_waypoints, normalized_end = validate_route_stops(
        start,
        waypoints,
        end,
    )
    route_points = [normalized_start, *normalized_waypoints, normalized_end]
    return [point_to_coord(point) for point in route_points]
