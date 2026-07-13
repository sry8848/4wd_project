import unittest

from src.tasks.edge_follow import (
    EDGE_BLOCKED_ON_PLANNED_EDGE,
    EDGE_CANCELED,
    EDGE_RECOVERED_TO_START_NODE,
    EDGE_RECOVERY_FAILED,
    EDGE_REACHED_NEXT_NODE,
    EdgeExecutionResult,
)
from src.tasks.grid_navigation import (
    HEADING_EAST,
    HEADING_NORTH,
    HEADING_SOUTH,
    HEADING_WEST,
    NAV_ARRIVED,
    NAV_CANCELED,
    NAV_FAILED,
    NAV_NO_PATH,
    GridNavigator,
)


class FakeMotor:
    def __init__(self):
        self.calls = []

    def spin_left(self, left_speed, right_speed):
        self.calls.append(("spin_left", left_speed, right_speed))

    def spin_right(self, left_speed, right_speed):
        self.calls.append(("spin_right", left_speed, right_speed))

    def brake(self):
        self.calls.append(("brake",))


class FakeEdgeFollower:
    def __init__(self, edge_statuses, recovery_statuses=None):
        self.edge_statuses = list(edge_statuses)
        self.recovery_statuses = list(recovery_statuses or [])
        self.execute_calls = []
        self.recover_calls = []

    def execute_planned_edge(
        self,
        current_heading,
        target_heading,
        max_seconds,
        cancel_requested_fn=None,
    ):
        self.execute_calls.append((current_heading, target_heading, max_seconds))
        if cancel_requested_fn is not None and cancel_requested_fn():
            return EdgeExecutionResult(status=EDGE_CANCELED)
        if self.edge_statuses:
            status = self.edge_statuses.pop(0)
        else:
            status = EDGE_REACHED_NEXT_NODE
        distance = 12.5 if status == EDGE_BLOCKED_ON_PLANNED_EDGE else None
        return EdgeExecutionResult(
            status=status,
            final_heading=target_heading,
            obstacle_distance_cm=distance,
        )

    def recover_to_start_node(
        self,
        return_heading=None,
        max_seconds=None,
        cancel_requested_fn=None,
    ):
        self.recover_calls.append((return_heading, max_seconds))
        if cancel_requested_fn is not None and cancel_requested_fn():
            return EdgeExecutionResult(status=EDGE_CANCELED)
        if self.recovery_statuses:
            status = self.recovery_statuses.pop(0)
        else:
            status = EDGE_RECOVERY_FAILED
        return EdgeExecutionResult(status=status, final_heading=return_heading)


class FakeClock:
    def __init__(self):
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)


class GridNavigatorTest(unittest.TestCase):
    def build_navigator(
        self,
        grid,
        edge_statuses,
        recovery_statuses=None,
        static_blocked_edges=None,
    ):
        self.motor = FakeMotor()
        self.edge_follower = FakeEdgeFollower(edge_statuses, recovery_statuses)
        self.clock = FakeClock()
        return GridNavigator(
            grid,
            self.edge_follower,
            self.motor,
            static_blocked_edges=static_blocked_edges,
            turn_speed=40,
            turn_seconds=0.3,
            uturn_seconds=0.7,
            edge_max_seconds=5,
            recovery_max_seconds=6,
            sleep_fn=self.clock.sleep,
        )

    def test_navigate_reaches_target_without_obstacles(self):
        navigator = self.build_navigator(
            [["A", "A", "A"]],
            [EDGE_REACHED_NEXT_NODE, EDGE_REACHED_NEXT_NODE],
        )

        result = navigator.navigate((0, 0), (0, 2), HEADING_EAST)

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(navigator.current_node, (0, 2))
        self.assertEqual(
            self.edge_follower.execute_calls,
            [
                (HEADING_EAST, HEADING_EAST, 5),
                (HEADING_EAST, HEADING_EAST, 5),
            ],
        )
        self.assertEqual(navigator.dynamic_blocked_edges, set())

    def test_navigate_blocks_planned_edge_recovers_then_replans(self):
        navigator = self.build_navigator(
            [
                ["A", "A"],
                ["A", "A"],
            ],
            [
                EDGE_BLOCKED_ON_PLANNED_EDGE,
                EDGE_REACHED_NEXT_NODE,
                EDGE_REACHED_NEXT_NODE,
                EDGE_REACHED_NEXT_NODE,
            ],
            recovery_statuses=[EDGE_RECOVERED_TO_START_NODE],
        )

        obstacle_results = []

        def report_obstacle(*args):
            obstacle_results.append(
                (args, len(self.edge_follower.execute_calls), len(self.edge_follower.recover_calls))
            )

        result = navigator.navigate(
            (0, 0),
            (0, 1),
            HEADING_EAST,
            obstacle_result_fn=report_obstacle,
        )

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(navigator.current_node, (0, 1))
        self.assertIn(frozenset({(0, 0), (0, 1)}), navigator.dynamic_blocked_edges)
        self.assertEqual(
            self.edge_follower.recover_calls,
            [(HEADING_EAST, 6)],
        )
        self.assertEqual(
            self.edge_follower.execute_calls,
            [
                (HEADING_EAST, HEADING_EAST, 5),
                (HEADING_EAST, HEADING_SOUTH, 5),
                (HEADING_SOUTH, HEADING_EAST, 5),
                (HEADING_EAST, HEADING_NORTH, 5),
            ],
        )
        self.assertEqual(
            obstacle_results,
            [
                (
                    (
                        (0, 0),
                        (0, 1),
                        12.5,
                        EDGE_RECOVERED_TO_START_NODE,
                        HEADING_EAST,
                    ),
                    1,
                    1,
                )
            ],
        )

    def test_navigate_fails_when_recovery_fails_after_dynamic_block(self):
        navigator = self.build_navigator(
            [
                ["A", "A"],
                ["A", "A"],
            ],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
            recovery_statuses=[EDGE_RECOVERY_FAILED],
        )

        obstacle_results = []
        result = navigator.navigate(
            (0, 0),
            (0, 1),
            HEADING_EAST,
            obstacle_result_fn=lambda *args: obstacle_results.append(args),
        )

        self.assertEqual(result, NAV_FAILED)
        self.assertEqual(navigator.current_node, (0, 0))
        self.assertIn(frozenset({(0, 0), (0, 1)}), navigator.dynamic_blocked_edges)
        self.assertEqual(self.motor.calls[-1], ("brake",))
        self.assertEqual(
            obstacle_results,
            [
                (
                    (0, 0),
                    (0, 1),
                    12.5,
                    EDGE_RECOVERY_FAILED,
                    HEADING_EAST,
                )
            ],
        )

    def test_navigate_returns_no_path_when_static_edges_exhaust_routes(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [],
            static_blocked_edges={frozenset({(0, 0), (0, 1)})},
        )

        result = navigator.navigate((0, 0), (0, 1), HEADING_EAST)

        self.assertEqual(result, NAV_NO_PATH)
        self.assertEqual(navigator.current_node, (0, 0))
        self.assertEqual(self.edge_follower.execute_calls, [])
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_navigate_delegates_turning_to_edge_executor(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_REACHED_NEXT_NODE],
        )

        result = navigator.navigate((0, 0), (0, 1), HEADING_NORTH)

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(self.edge_follower.execute_calls, [(HEADING_NORTH, HEADING_EAST, 5)])
        self.assertEqual(self.motor.calls, [("brake",)])
        self.assertEqual(navigator.current_heading, HEADING_EAST)

    def test_navigate_cancels_before_starting_an_edge(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_REACHED_NEXT_NODE],
        )

        result = navigator.navigate(
            (0, 0),
            (0, 1),
            HEADING_EAST,
            cancel_requested_fn=lambda: True,
        )

        self.assertEqual(result, NAV_CANCELED)
        self.assertEqual(self.edge_follower.execute_calls, [])
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_navigate_reports_each_reached_trusted_node(self):
        navigator = self.build_navigator(
            [["A", "A", "A"]],
            [EDGE_REACHED_NEXT_NODE, EDGE_REACHED_NEXT_NODE],
        )
        reached_nodes = []

        result = navigator.navigate(
            (0, 0),
            (0, 2),
            HEADING_EAST,
            node_reached_fn=lambda node, heading: reached_nodes.append((node, heading)),
        )

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(
            reached_nodes,
            [
                ((0, 1), HEADING_EAST),
                ((0, 2), HEADING_EAST),
            ],
        )

    def test_navigate_cancels_after_reporting_a_reached_node(self):
        navigator = self.build_navigator(
            [["A", "A", "A"]],
            [EDGE_REACHED_NEXT_NODE, EDGE_REACHED_NEXT_NODE],
        )
        reached_nodes = []

        result = navigator.navigate(
            (0, 0),
            (0, 2),
            HEADING_EAST,
            cancel_requested_fn=lambda: bool(reached_nodes),
            node_reached_fn=lambda node, heading: reached_nodes.append((node, heading)),
        )

        self.assertEqual(result, NAV_CANCELED)
        self.assertEqual(reached_nodes, [((0, 1), HEADING_EAST)])
        self.assertEqual(navigator.current_node, (0, 1))
        self.assertEqual(len(self.edge_follower.execute_calls), 1)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_graceful_cancel_reaches_next_forward_node_before_stopping(self):
        navigator = self.build_navigator(
            [["A", "A", "A"]],
            [EDGE_REACHED_NEXT_NODE, EDGE_REACHED_NEXT_NODE],
        )
        reached_nodes = []

        result = navigator.navigate(
            (0, 0),
            (0, 2),
            HEADING_EAST,
            stop_at_next_node_fn=lambda: True,
            node_reached_fn=lambda node, heading: reached_nodes.append((node, heading)),
        )

        self.assertEqual(result, NAV_CANCELED)
        self.assertEqual(reached_nodes, [((0, 1), HEADING_EAST)])
        self.assertEqual(navigator.current_node, (0, 1))
        self.assertEqual(
            self.edge_follower.execute_calls,
            [(HEADING_EAST, HEADING_EAST, 5)],
        )
        self.assertEqual(self.motor.calls[-1], ("brake",))


if __name__ == "__main__":
    unittest.main()
