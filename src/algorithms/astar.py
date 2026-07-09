"""A* path planning on a rectangular grid.

本模块只做二维网格路径规划，不读取传感器，不控制电机。
路径执行层需要另行把坐标路径转换成小车的前进、左转、右转动作。
"""

import heapq
from dataclasses import dataclass
from itertools import count
from typing import Optional, Tuple


PASSABLE = "A"
OBSTACLE = "X"
Coordinate = Tuple[int, int]


@dataclass(frozen=True)
class Node:
    """A* 搜索节点。

    参数说明：
    position: 当前格子的坐标，格式为零基索引 (row, col)。
    parent: 从哪个节点走到当前节点；用于搜索结束后回溯路径。
    g: 从起点走到当前节点的真实代价。
    h: 从当前节点到终点的估计代价。
    """

    position: Coordinate
    parent: Optional["Node"] = None
    g: int = 0
    h: int = 0

    @property
    def f(self):
        """返回 A* 排序使用的总代价 g + h。"""
        return self.g + self.h


def heuristic(a, b):
    """计算两个网格坐标之间的曼哈顿距离。

    参数说明：
    a: 第一个坐标，格式为 (row, col)。
    b: 第二个坐标，格式为 (row, col)。
    """
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(grid, start, end):
    """在二维网格中搜索从起点到终点的最短路径。

    参数说明：
    grid: 矩形二维网格，只允许使用 "A" 表示可通行，"X" 表示障碍物。
    start: 起点坐标，格式为零基索引 (row, col)。
    end: 终点坐标，格式为零基索引 (row, col)。

    返回值：
    找到路径时返回包含起点和终点的坐标列表；无路可走时返回 None。
    """
    height, width = _validate_grid(grid)
    _validate_coordinate("start", start, height, width)
    _validate_coordinate("end", end, height, width)

    if grid[start[0]][start[1]] == OBSTACLE:
        raise ValueError("start 不能是障碍物")
    if grid[end[0]][end[1]] == OBSTACLE:
        raise ValueError("end 不能是障碍物")

    start_node = Node(start, h=heuristic(start, end))
    open_heap = []
    push_order = count()
    best_costs = {start: 0}
    closed_positions = set()
    heapq.heappush(open_heap, (start_node.f, start_node.h, next(push_order), start_node))

    while open_heap:
        current_node = heapq.heappop(open_heap)[3]
        if current_node.position in closed_positions:
            continue

        if current_node.position == end:
            path = []
            while current_node is not None:
                path.append(current_node.position)
                current_node = current_node.parent
            return path[::-1]

        closed_positions.add(current_node.position)

        # 只允许上下左右四连通移动；网格路径以后再由任务层转换成小车动作。
        for neighbor in _neighbors(current_node.position, height, width):
            if neighbor in closed_positions or grid[neighbor[0]][neighbor[1]] == OBSTACLE:
                continue

            next_g = current_node.g + 1
            if next_g >= best_costs.get(neighbor, float("inf")):
                continue

            next_node = Node(
                neighbor,
                parent=current_node,
                g=next_g,
                h=heuristic(neighbor, end),
            )
            best_costs[neighbor] = next_g
            heapq.heappush(open_heap, (next_node.f, next_node.h, next(push_order), next_node))

    return None


def grid_to_string(grid):
    """把网格转换成适合打印或邮件正文展示的字符串。

    参数说明：
    grid: 二维网格，例如 [["A", "X"], ["A", "A"]]。
    """
    return "".join(" ".join(row) + "\n" for row in grid)


def format_path(path):
    """把零基坐标路径转换成 A1、B2 这类展示格式。

    参数说明：
    path: astar() 返回的坐标路径，例如 [(0, 0), (1, 0)]。
    """
    formatted_path = []
    for row, col in path:
        formatted_path.append(f"{chr(row + ord('A'))}{col + 1}")
    return formatted_path


def _validate_grid(grid):
    # grid 来自外部调用方，是算法模块的信任边界，必须先校验契约。
    if not grid or not grid[0]:
        raise ValueError("grid 不能为空")

    width = len(grid[0])
    for row in grid:
        if len(row) != width:
            raise ValueError("grid 必须是矩形二维网格")
        for cell in row:
            if cell not in (PASSABLE, OBSTACLE):
                raise ValueError('grid 只能包含 "A" 和 "X"')

    return len(grid), width


def _validate_coordinate(name, coordinate, height, width):
    if not isinstance(coordinate, tuple) or len(coordinate) != 2:
        raise ValueError(f"{name} 必须是 (row, col) 坐标")

    row, col = coordinate
    if not isinstance(row, int) or not isinstance(col, int):
        raise ValueError(f"{name} 的 row 和 col 必须是整数")

    if row < 0 or row >= height or col < 0 or col >= width:
        raise ValueError(f"{name} 超出 grid 范围")


def _neighbors(position, height, width):
    row, col = position
    for next_position in (
        (row, col - 1),
        (row - 1, col),
        (row, col + 1),
        (row + 1, col),
    ):
        next_row, next_col = next_position
        if 0 <= next_row < height and 0 <= next_col < width:
            yield next_position
