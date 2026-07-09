"""Grid-level navigation state machine for black-line maps."""

import time

from src.algorithms.astar import astar
from src.tasks.edge_follow import (
    EDGE_BLOCKED_ON_PLANNED_EDGE,
    EDGE_REACHED_NEXT_NODE,
    EDGE_RECOVERED_TO_START_NODE,
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
    """Maintain trusted grid position and re-plan when an edge is blocked.

    Parameters:
    grid: Rectangular A* grid where "A" is passable and "X" is a node obstacle.
    edge_follower: Edge executor with execute_planned_edge() and
        recover_to_start_node().
    motor: Motor object used for final safety braking.
    static_blocked_edges: Known blocked undirected edges before navigation.
    turn_speed/turn_seconds/uturn_seconds/sleep_fn: Kept for older callers; edge
        turning is now handled by EdgeFollower.
    edge_max_seconds: Timeout for one planned edge execution.
    recovery_max_seconds: Timeout for returning to the start node after a block.
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
        """Navigate from start to end using trusted-node state transitions.

        Parameters:
        start: Start coordinate as (row, col).
        end: Target coordinate as (row, col).
        initial_heading: Trusted heading at the start node.
        """
        if initial_heading not in _HEADINGS:
            raise ValueError("initial_heading must be north/east/south/west")

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
            planned_edge = frozenset({self.current_node, next_node})

            edge_result = self.edge_follower.execute_planned_edge(
                self.current_heading,
                target_heading,
                self.edge_max_seconds,
            )
            edge_status = _result_status(edge_result)

            if edge_status == EDGE_REACHED_NEXT_NODE:
                self.current_node = next_node
                self.current_heading = target_heading
                continue

            if edge_status == EDGE_BLOCKED_ON_PLANNED_EDGE:
                self.dynamic_blocked_edges.add(planned_edge)
                return_heading = _opposite_heading(target_heading)
                recovery_result = self.edge_follower.recover_to_start_node(
                    return_heading=return_heading,
                    max_seconds=self.recovery_max_seconds,
                )
                if _result_status(recovery_result) != EDGE_RECOVERED_TO_START_NODE:
                    self.motor.brake()
                    return NAV_FAILED

                self.current_heading = _result_final_heading(
                    recovery_result,
                    default=return_heading,
                )
                continue

            self.motor.brake()
            return NAV_FAILED

        self.motor.brake()
        return NAV_ARRIVED

    def _all_blocked_edges(self):
        return self.static_blocked_edges | self.dynamic_blocked_edges


def _result_status(result):
    return result.status if hasattr(result, "status") else result


def _result_final_heading(result, default=None):
    return getattr(result, "final_heading", None) or default


def _heading_between(current_node, next_node):
    """Return the heading needed to move between adjacent grid nodes.

    Parameters:
    current_node: Current coordinate as (row, col).
    next_node: Adjacent coordinate as (row, col).
    """
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

    raise ValueError("current_node and next_node must be adjacent")


def _opposite_heading(heading):
    """Return the opposite compass heading.

    Parameters:
    heading: One of north/east/south/west.
    """
    if heading not in _HEADINGS:
        raise ValueError("heading must be north/east/south/west")

    return _HEADINGS[(_HEADINGS.index(heading) + 2) % len(_HEADINGS)]
