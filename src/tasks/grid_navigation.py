"""Grid-level navigation state machine for black-line maps."""

import time

from src.algorithms.astar import astar
from src.tasks.edge_follow import (
    EDGE_BLOCKED_BEFORE_ENTERING,
    EDGE_BLOCKED_MID_EDGE,
    EDGE_REACHED_NODE,
    EDGE_RECOVERED,
)


HEADING_NORTH = "north"
HEADING_EAST = "east"
HEADING_SOUTH = "south"
HEADING_WEST = "west"

NAV_ARRIVED = "arrived"
NAV_NO_PATH = "no_path"
NAV_FAILED = "failed"

_HEADINGS = (HEADING_NORTH, HEADING_EAST, HEADING_SOUTH, HEADING_WEST)


class GridNavigator:
    """维护网格点到点导航状态，并在遇障碍时封边重规划。

    参数说明：
    grid: A* 使用的矩形地图，"A" 表示可走，"X" 表示节点障碍。
    edge_follower: 执行单条边的对象，通常是 EdgeFollower。
    motor: 电机对象，提供 spin_left/spin_right/brake。
    static_blocked_edges: 已知不可通行边集合。
    turn_speed: 原地转向时左右电机 PWM 占空比。
    turn_seconds: 90 度转向持续时间。
    uturn_seconds: 180 度转向持续时间。
    edge_max_seconds: 执行一条边的超时秒数。
    recovery_max_seconds: 中途障碍后回到上一节点的超时秒数。
    sleep_fn: 等待函数，实机默认 time.sleep，测试可注入。
    """

    def __init__(
        self,
        grid,
        edge_follower,
        motor,
        static_blocked_edges=None,
        turn_speed=30,
        turn_seconds=0.5,
        uturn_seconds=1.2,
        edge_max_seconds=5,
        recovery_max_seconds=5,
        sleep_fn=None,
    ):
        self.grid = grid
        self.edge_follower = edge_follower
        self.motor = motor
        self.static_blocked_edges = set(static_blocked_edges or [])
        self.dynamic_blocked_edges = set()
        self.turn_speed = turn_speed
        self.turn_seconds = turn_seconds
        self.uturn_seconds = uturn_seconds
        self.edge_max_seconds = edge_max_seconds
        self.recovery_max_seconds = recovery_max_seconds
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self.current_node = None
        self.target_node = None
        self.current_heading = None

    def navigate(self, start, end, initial_heading):
        """从 start 导航到 end，返回导航结果状态。

        参数说明：
        start: 起点坐标，格式为 (row, col)。
        end: 终点坐标，格式为 (row, col)。
        initial_heading: 初始朝向，必须是 north/east/south/west 之一。
        """
        if initial_heading not in _HEADINGS:
            raise ValueError("initial_heading 必须是 north/east/south/west")

        self.current_node = start
        self.target_node = end
        self.current_heading = initial_heading
        self.dynamic_blocked_edges = set()

        while self.current_node != self.target_node:
            path = astar(
                self.grid,
                self.current_node,
                self.target_node,
                blocked_edges=self._all_blocked_edges(),
            )
            if path is None:
                self.motor.brake()
                return NAV_NO_PATH

            next_node = path[1]
            target_heading = _heading_between(self.current_node, next_node)
            self._turn_to_heading(target_heading)

            edge_result = self.edge_follower.follow_edge(self.edge_max_seconds)
            current_edge = frozenset({self.current_node, next_node})

            if edge_result == EDGE_REACHED_NODE:
                self.current_node = next_node
                continue

            if edge_result == EDGE_BLOCKED_BEFORE_ENTERING:
                self.dynamic_blocked_edges.add(current_edge)
                continue

            if edge_result == EDGE_BLOCKED_MID_EDGE:
                recovery_result = self.edge_follower.recover_to_start_node(
                    self.recovery_max_seconds
                )
                if recovery_result != EDGE_RECOVERED:
                    self.motor.brake()
                    return NAV_FAILED

                self.dynamic_blocked_edges.add(current_edge)
                continue

            self.motor.brake()
            return NAV_FAILED

        self.motor.brake()
        return NAV_ARRIVED

    def _all_blocked_edges(self):
        return self.static_blocked_edges | self.dynamic_blocked_edges

    def _turn_to_heading(self, target_heading):
        current_index = _HEADINGS.index(self.current_heading)
        target_index = _HEADINGS.index(target_heading)
        diff = (target_index - current_index) % len(_HEADINGS)

        if diff == 1:
            self._spin_right(self.turn_seconds)
        elif diff == 2:
            self._spin_left(self.uturn_seconds)
        elif diff == 3:
            self._spin_left(self.turn_seconds)

        self.current_heading = target_heading

    def _spin_left(self, seconds):
        self.motor.spin_left(self.turn_speed, self.turn_speed)
        self._sleep(seconds)
        self.motor.brake()

    def _spin_right(self, seconds):
        self.motor.spin_right(self.turn_speed, self.turn_speed)
        self._sleep(seconds)
        self.motor.brake()


def _heading_between(current_node, next_node):
    current_row, current_col = current_node
    next_row, next_col = next_node

    if next_row == current_row - 1 and next_col == current_col:
        return HEADING_NORTH
    if next_row == current_row + 1 and next_col == current_col:
        return HEADING_SOUTH
    if next_col == current_col + 1 and next_row == current_row:
        return HEADING_EAST
    if next_col == current_col - 1 and next_row == current_row:
        return HEADING_WEST

    raise ValueError("current_node 和 next_node 必须相邻")
