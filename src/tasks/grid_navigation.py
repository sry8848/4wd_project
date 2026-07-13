"""Grid-level navigation state machine for black-line maps."""

import time

from src.algorithms.astar import astar, format_path
from src.tasks.edge_follow import (
    EDGE_BLOCKED_ON_PLANNED_EDGE,
    EDGE_CANCELED,
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
NAV_CANCELED = "canceled"

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
    debug_fn: Optional callback(message) for field-test plan/result logs.
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
        debug_fn=None,
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
        self._debug = debug_fn
        self.current_node = None
        self.target_node = None
        self.current_heading = None

    def _log(self, message):
        """Emit one debug line when a debug callback is configured."""
        if self._debug is not None:
            self._debug(message)

    def navigate(
        self,
        start,
        end,
        initial_heading,
        cancel_requested_fn=None,
        node_reached_fn=None,
        stop_at_next_node_fn=None,
        obstacle_result_fn=None,
    ):
        """Navigate from start to end using trusted-node state transitions.

        Parameters:
        start: Start coordinate as (row, col).
        end: Target coordinate as (row, col).
        initial_heading: Trusted heading at the start node.
        cancel_requested_fn: Optional callback returning True when navigation must stop.
        node_reached_fn: Optional callback(node, heading) after reaching a trusted node.
        stop_at_next_node_fn: Optional callback for a graceful stop. When requested
            during an edge, finish that edge and stop at the confirmed next node.
        obstacle_result_fn: Optional callback receiving the blocked edge, confirmed
            distance, recovery result, and final heading after recovery finishes.

        Steps:
        Check cancellation before each planning/execution phase, pass the same signal
        into EdgeFollower, and publish each confirmed node after updating trusted state.
        """
        if initial_heading not in _HEADINGS:
            raise ValueError("initial_heading must be north/east/south/west")

        self.current_node = start
        self.target_node = end
        self.current_heading = initial_heading
        self.dynamic_blocked_edges = set()
        self._log(
            f"nav start={_fmt_node(start)} end={_fmt_node(end)} "
            f"heading={initial_heading}"
        )
        if self._cancel_requested(cancel_requested_fn):
            return NAV_CANCELED

        while self.current_node != self.target_node:
            if self._cancel_requested(cancel_requested_fn):
                return NAV_CANCELED
            path = astar(
                self.grid,
                self.current_node,
                self.target_node,
                blocked_edges=self._all_blocked_edges(),
            )
            if path is None:
                self.motor.brake()
                self._log(
                    f"nav no_path at={_fmt_node(self.current_node)} "
                    f"heading={self.current_heading} "
                    f"dynamic_blocked={len(self.dynamic_blocked_edges)}"
                )
                return NAV_NO_PATH

            next_node = path[1]
            target_heading = _heading_between(self.current_node, next_node)
            planned_edge = frozenset({self.current_node, next_node})
            self._log(
                f"nav plan path={'->'.join(format_path(path))} "
                f"edge={_fmt_node(self.current_node)}-{_fmt_node(next_node)} "
                f"heading={self.current_heading}->{target_heading}"
            )

            edge_result = self.edge_follower.execute_planned_edge(
                self.current_heading,
                target_heading,
                self.edge_max_seconds,
                cancel_requested_fn=cancel_requested_fn,
            )
            edge_status = _result_status(edge_result)
            self._log(
                f"nav edge_result status={edge_status} "
                f"reason={getattr(edge_result, 'reason', None)} "
                f"at={_fmt_node(self.current_node)}"
            )

            if edge_status == EDGE_CANCELED:
                return self._finish_canceled()

            if edge_status == EDGE_REACHED_NEXT_NODE:
                self.current_node = next_node
                self.current_heading = target_heading
                self._log(
                    f"nav reached node={_fmt_node(self.current_node)} "
                    f"heading={self.current_heading}"
                )
                if node_reached_fn is not None:
                    try:
                        node_reached_fn(self.current_node, self.current_heading)
                    except Exception:
                        self.motor.brake()
                        raise
                if self._stop_at_node_requested(stop_at_next_node_fn):
                    return NAV_CANCELED
                if self._cancel_requested(cancel_requested_fn):
                    return NAV_CANCELED
                continue

            if edge_status == EDGE_BLOCKED_ON_PLANNED_EDGE:
                self.dynamic_blocked_edges.add(planned_edge)
                return_heading = target_heading
                self._log(
                    f"nav block edge={_fmt_node(self.current_node)}-"
                    f"{_fmt_node(next_node)} recover_heading={return_heading}"
                )
                recovery_result = self.edge_follower.recover_to_start_node(
                    return_heading=return_heading,
                    max_seconds=self.recovery_max_seconds,
                    cancel_requested_fn=cancel_requested_fn,
                )
                recovery_status = _result_status(recovery_result)
                self._log(
                    f"nav recovery_result status={recovery_status} "
                    f"reason={getattr(recovery_result, 'reason', None)}"
                )
                if recovery_status == EDGE_CANCELED:
                    return self._finish_canceled()
                if recovery_status != EDGE_RECOVERED_TO_START_NODE:
                    self.motor.brake()
                    if obstacle_result_fn is not None:
                        obstacle_result_fn(
                            self.current_node,
                            next_node,
                            edge_result.obstacle_distance_cm,
                            recovery_status,
                            _result_final_heading(recovery_result),
                        )
                    return NAV_FAILED

                self.current_heading = _result_final_heading(
                    recovery_result,
                    default=return_heading,
                )
                self._log(
                    f"nav recovered at={_fmt_node(self.current_node)} "
                    f"heading={self.current_heading}"
                )
                if obstacle_result_fn is not None:
                    obstacle_result_fn(
                        self.current_node,
                        next_node,
                        edge_result.obstacle_distance_cm,
                        recovery_status,
                        self.current_heading,
                    )
                if self._stop_at_node_requested(stop_at_next_node_fn):
                    return NAV_CANCELED
                continue

            self.motor.brake()
            self._log(
                f"nav failed status={edge_status} "
                f"at={_fmt_node(self.current_node)} heading={self.current_heading}"
            )
            return NAV_FAILED

        self.motor.brake()
        self._log(f"nav arrived at={_fmt_node(self.current_node)}")
        return NAV_ARRIVED

    def _cancel_requested(self, cancel_requested_fn):
        """Check external cancellation and brake before returning or raising.

        Parameters:
        cancel_requested_fn: Optional zero-argument callback returning a boolean.

        Steps:
        Treat a missing callback as active navigation. Brake when cancellation is
        requested or when the callback itself raises.
        """
        if cancel_requested_fn is None:
            return False
        try:
            requested = bool(cancel_requested_fn())
        except Exception:
            self.motor.brake()
            raise
        if requested:
            self.motor.brake()
            self._log(f"nav canceled at={_fmt_node(self.current_node)}")
        return requested

    def _finish_canceled(self):
        """Brake and convert a lower-level canceled result into NAV_CANCELED."""
        self.motor.brake()
        self._log(f"nav canceled at={_fmt_node(self.current_node)}")
        return NAV_CANCELED

    def _stop_at_node_requested(self, stop_at_next_node_fn):
        """Check a graceful-stop request only while positioned at a trusted node.

        Parameters:
        stop_at_next_node_fn: Optional zero-argument callback. It is deliberately
            not passed into EdgeFollower, so a request made between nodes cannot
            stop the motors until the planned forward node is confirmed.
        """

        if stop_at_next_node_fn is None:
            return False
        try:
            requested = bool(stop_at_next_node_fn())
        except Exception:
            self.motor.brake()
            raise
        if requested:
            self.motor.brake()
            self._log(f"nav graceful_stop at={_fmt_node(self.current_node)}")
        return requested

    def _all_blocked_edges(self):
        return self.static_blocked_edges | self.dynamic_blocked_edges


def _fmt_node(node):
    """Format one (row, col) node as A1-style text for debug logs."""
    return format_path([node])[0]


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
