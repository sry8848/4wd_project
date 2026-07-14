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
    OBSTACLE_ACTION_BLOCK_AND_RECOVER,
    OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE,
    GridNavigator,
    ObstacleDecision,
)


def block_and_recover(_from_node, _to_node, _distance_cm):
    return ObstacleDecision(OBSTACLE_ACTION_BLOCK_AND_RECOVER)


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
    def __init__(self, edge_statuses, recovery_statuses=None, resume_statuses=None):
        self.edge_statuses = list(edge_statuses)
        self.recovery_statuses = list(recovery_statuses or [])
        self.resume_statuses = list(resume_statuses or [])
        self.execute_calls = []
        self.resume_calls = []
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

    def resume_planned_edge(
        self,
        target_heading,
        max_seconds,
        cancel_requested_fn=None,
    ):
        self.resume_calls.append((target_heading, max_seconds))
        if cancel_requested_fn is not None and cancel_requested_fn():
            return EdgeExecutionResult(status=EDGE_CANCELED)
        if self.resume_statuses:
            status = self.resume_statuses.pop(0)
        else:
            status = EDGE_REACHED_NEXT_NODE
        distance = 9.5 if status == EDGE_BLOCKED_ON_PLANNED_EDGE else None
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
        resume_statuses=None,
        static_blocked_edges=None,
    ):
        self.motor = FakeMotor()
        self.edge_follower = FakeEdgeFollower(
            edge_statuses,
            recovery_statuses,
            resume_statuses,
        )
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

        result = navigator.navigate(
            (0, 0), (0, 2), HEADING_EAST, block_and_recover
        )

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
            block_and_recover,
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
                        ObstacleDecision(OBSTACLE_ACTION_BLOCK_AND_RECOVER),
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
            block_and_recover,
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
                    ObstacleDecision(OBSTACLE_ACTION_BLOCK_AND_RECOVER),
                    EDGE_RECOVERY_FAILED,
                    HEADING_EAST,
                )
            ],
        )

    def test_continue_current_edge_reports_while_stopped_and_reaches_next_node(self):
        context = object()
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
            resume_statuses=[EDGE_REACHED_NEXT_NODE],
        )
        decisions = []
        obstacle_results = []
        reached_nodes = []

        def decide(from_node, to_node, distance_cm):
            decisions.append((from_node, to_node, distance_cm, self.motor.calls[-1]))
            return ObstacleDecision(
                OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE,
                context=context,
            )

        def report(*args):
            obstacle_results.append(
                (args, self.motor.calls[-1], len(self.edge_follower.resume_calls))
            )

        result = navigator.navigate(
            (0, 0),
            (0, 1),
            HEADING_EAST,
            decide,
            node_reached_fn=lambda node, heading: reached_nodes.append((node, heading)),
            obstacle_result_fn=report,
        )

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(decisions, [((0, 0), (0, 1), 12.5, ("brake",))])
        self.assertEqual(self.edge_follower.resume_calls, [(HEADING_EAST, 5)])
        self.assertEqual(self.edge_follower.recover_calls, [])
        self.assertEqual(navigator.dynamic_blocked_edges, set())
        self.assertEqual(navigator.current_node, (0, 1))
        self.assertEqual(navigator.current_heading, HEADING_EAST)
        self.assertEqual(reached_nodes, [((0, 1), HEADING_EAST)])
        reported_args, last_motor_call, resume_count = obstacle_results[0]
        self.assertEqual(last_motor_call, ("brake",))
        self.assertEqual(resume_count, 0)
        self.assertIs(reported_args[3].context, context)
        self.assertEqual(reported_args[4], OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE)
        self.assertEqual(reported_args[5], HEADING_EAST)

    def test_continue_current_edge_reenters_decision_for_second_obstacle(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
            resume_statuses=[
                EDGE_BLOCKED_ON_PLANNED_EDGE,
                EDGE_REACHED_NEXT_NODE,
            ],
        )
        distances = []

        def decide(_from_node, _to_node, distance_cm):
            distances.append(distance_cm)
            return ObstacleDecision(OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE)

        result = navigator.navigate((0, 0), (0, 1), HEADING_EAST, decide)

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(distances, [12.5, 9.5])
        self.assertEqual(
            self.edge_follower.resume_calls,
            [(HEADING_EAST, 5), (HEADING_EAST, 5)],
        )
        self.assertEqual(navigator.dynamic_blocked_edges, set())

    def test_graceful_stop_during_decision_recovers_before_canceling(self):
        context = object()
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
            recovery_statuses=[EDGE_RECOVERED_TO_START_NODE],
        )
        decision_finished = []
        obstacle_results = []

        def decide(_from_node, _to_node, _distance_cm):
            decision_finished.append(True)
            return ObstacleDecision(
                OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE,
                context=context,
            )

        result = navigator.navigate(
            (0, 0),
            (0, 1),
            HEADING_EAST,
            decide,
            stop_at_next_node_fn=lambda: bool(decision_finished),
            obstacle_result_fn=lambda *args: obstacle_results.append(args),
        )

        self.assertEqual(result, NAV_CANCELED)
        self.assertEqual(self.edge_follower.resume_calls, [])
        self.assertEqual(self.edge_follower.recover_calls, [(HEADING_EAST, 6)])
        self.assertEqual(navigator.current_node, (0, 0))
        self.assertEqual(
            obstacle_results[0][3].action,
            OBSTACLE_ACTION_BLOCK_AND_RECOVER,
        )
        self.assertIs(obstacle_results[0][3].context, context)
        self.assertEqual(obstacle_results[0][4], EDGE_RECOVERED_TO_START_NODE)

    def test_emergency_cancel_after_decision_stops_without_recovery(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
        )
        emergency = []

        def decide(_from_node, _to_node, _distance_cm):
            emergency.append(True)
            return ObstacleDecision(OBSTACLE_ACTION_BLOCK_AND_RECOVER)

        result = navigator.navigate(
            (0, 0),
            (0, 1),
            HEADING_EAST,
            decide,
            cancel_requested_fn=lambda: bool(emergency),
        )

        self.assertEqual(result, NAV_CANCELED)
        self.assertEqual(self.edge_follower.recover_calls, [])
        self.assertEqual(navigator.dynamic_blocked_edges, set())
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_obstacle_decision_contract_errors_brake_and_raise(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_REACHED_NEXT_NODE],
        )
        with self.assertRaisesRegex(TypeError, "must be callable"):
            navigator.navigate((0, 0), (0, 1), HEADING_EAST, None)
        self.assertEqual(self.edge_follower.execute_calls, [])
        self.assertEqual(self.motor.calls[-1], ("brake",))

        cases = (
            (lambda _from, _to, _distance: "continue_current_edge", TypeError),
            (
                lambda _from, _to, _distance: ObstacleDecision("unknown"),
                ValueError,
            ),
        )
        for decision_fn, error_type in cases:
            with self.subTest(error_type=error_type):
                navigator = self.build_navigator(
                    [["A", "A"]],
                    [EDGE_BLOCKED_ON_PLANNED_EDGE],
                )
                with self.assertRaises(error_type):
                    navigator.navigate((0, 0), (0, 1), HEADING_EAST, decision_fn)
                self.assertEqual(self.motor.calls[-1], ("brake",))
                self.assertEqual(navigator.current_node, (0, 0))

        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
        )

        def fail_decision(_from, _to, _distance):
            raise RuntimeError("decision failed")

        with self.assertRaisesRegex(RuntimeError, "decision failed"):
            navigator.navigate((0, 0), (0, 1), HEADING_EAST, fail_decision)
        self.assertEqual(self.motor.calls[-1], ("brake",))
        self.assertEqual(navigator.current_node, (0, 0))

    def test_obstacle_callback_errors_keep_the_car_stopped(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
            resume_statuses=[EDGE_REACHED_NEXT_NODE],
        )

        def fail_result_callback(*_args):
            raise RuntimeError("record failed")

        with self.assertRaisesRegex(RuntimeError, "record failed"):
            navigator.navigate(
                (0, 0),
                (0, 1),
                HEADING_EAST,
                lambda _from, _to, _distance: ObstacleDecision(
                    OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE
                ),
                obstacle_result_fn=fail_result_callback,
            )

        self.assertEqual(self.edge_follower.resume_calls, [])
        self.assertEqual(self.motor.calls[-1], ("brake",))
        self.assertEqual(navigator.current_node, (0, 0))

    def test_resume_failure_does_not_publish_the_next_node(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_ON_PLANNED_EDGE],
            resume_statuses=["line_lost"],
        )
        reached_nodes = []

        result = navigator.navigate(
            (0, 0),
            (0, 1),
            HEADING_EAST,
            lambda _from, _to, _distance: ObstacleDecision(
                OBSTACLE_ACTION_CONTINUE_CURRENT_EDGE
            ),
            node_reached_fn=lambda node, heading: reached_nodes.append((node, heading)),
        )

        self.assertEqual(result, NAV_FAILED)
        self.assertEqual(navigator.current_node, (0, 0))
        self.assertEqual(reached_nodes, [])
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_navigate_returns_no_path_when_static_edges_exhaust_routes(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [],
            static_blocked_edges={frozenset({(0, 0), (0, 1)})},
        )

        result = navigator.navigate(
            (0, 0), (0, 1), HEADING_EAST, block_and_recover
        )

        self.assertEqual(result, NAV_NO_PATH)
        self.assertEqual(navigator.current_node, (0, 0))
        self.assertEqual(self.edge_follower.execute_calls, [])
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_navigate_delegates_turning_to_edge_executor(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_REACHED_NEXT_NODE],
        )

        result = navigator.navigate(
            (0, 0), (0, 1), HEADING_NORTH, block_and_recover
        )

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
            block_and_recover,
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
            block_and_recover,
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
            block_and_recover,
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
            block_and_recover,
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
