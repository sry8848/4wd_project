import unittest

from src.tasks.edge_follow import (
    EDGE_BLOCKED_BEFORE_ENTERING,
    EDGE_BLOCKED_MID_EDGE,
    EDGE_REACHED_NODE,
    EDGE_RECOVERED,
    EDGE_RECOVERY_FAILED,
)
from src.tasks.grid_navigation import (
    HEADING_EAST,
    HEADING_NORTH,
    NAV_ARRIVED,
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
    def __init__(self, follow_results, recover_results=None):
        self.follow_results = list(follow_results)
        self.recover_results = list(recover_results or [])
        self.follow_calls = []
        self.recover_calls = []

    def follow_edge(self, max_seconds):
        self.follow_calls.append(max_seconds)
        if self.follow_results:
            return self.follow_results.pop(0)
        return EDGE_REACHED_NODE

    def recover_to_start_node(self, max_seconds):
        self.recover_calls.append(max_seconds)
        if self.recover_results:
            return self.recover_results.pop(0)
        return EDGE_RECOVERY_FAILED


class FakeClock:
    def __init__(self):
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)


class GridNavigatorTest(unittest.TestCase):
    def build_navigator(self, grid, follow_results, recover_results=None):
        self.motor = FakeMotor()
        self.edge_follower = FakeEdgeFollower(follow_results, recover_results)
        self.clock = FakeClock()
        return GridNavigator(
            grid,
            self.edge_follower,
            self.motor,
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
            [EDGE_REACHED_NODE, EDGE_REACHED_NODE],
        )

        result = navigator.navigate((0, 0), (0, 2), HEADING_EAST)

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(navigator.current_node, (0, 2))
        self.assertEqual(self.edge_follower.follow_calls, [5, 5])
        self.assertEqual(navigator.dynamic_blocked_edges, set())

    def test_navigate_blocks_edge_and_replans_when_obstacle_is_seen_before_entering(self):
        navigator = self.build_navigator(
            [
                ["A", "A"],
                ["A", "A"],
            ],
            [
                EDGE_BLOCKED_BEFORE_ENTERING,
                EDGE_REACHED_NODE,
                EDGE_REACHED_NODE,
                EDGE_REACHED_NODE,
            ],
        )

        result = navigator.navigate((0, 0), (0, 1), HEADING_EAST)

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(navigator.current_node, (0, 1))
        self.assertIn(frozenset({(0, 0), (0, 1)}), navigator.dynamic_blocked_edges)
        self.assertEqual(self.edge_follower.follow_calls, [5, 5, 5, 5])

    def test_navigate_recovers_to_current_node_then_replans_after_mid_edge_obstacle(self):
        navigator = self.build_navigator(
            [
                ["A", "A"],
                ["A", "A"],
            ],
            [
                EDGE_BLOCKED_MID_EDGE,
                EDGE_REACHED_NODE,
                EDGE_REACHED_NODE,
                EDGE_REACHED_NODE,
            ],
            recover_results=[EDGE_RECOVERED],
        )

        result = navigator.navigate((0, 0), (0, 1), HEADING_EAST)

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(navigator.current_node, (0, 1))
        self.assertEqual(self.edge_follower.recover_calls, [6])
        self.assertIn(frozenset({(0, 0), (0, 1)}), navigator.dynamic_blocked_edges)

    def test_navigate_returns_no_path_when_blocking_current_edge_exhausts_routes(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_BLOCKED_BEFORE_ENTERING],
        )

        result = navigator.navigate((0, 0), (0, 1), HEADING_EAST)

        self.assertEqual(result, NAV_NO_PATH)
        self.assertEqual(navigator.current_node, (0, 0))
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_navigate_fails_when_mid_edge_recovery_fails(self):
        navigator = self.build_navigator(
            [
                ["A", "A"],
                ["A", "A"],
            ],
            [EDGE_BLOCKED_MID_EDGE],
            recover_results=[EDGE_RECOVERY_FAILED],
        )

        result = navigator.navigate((0, 0), (0, 1), HEADING_EAST)

        self.assertEqual(result, NAV_FAILED)
        self.assertEqual(navigator.current_node, (0, 0))
        self.assertEqual(navigator.dynamic_blocked_edges, set())
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_navigate_turns_right_from_north_to_east_before_following_edge(self):
        navigator = self.build_navigator(
            [["A", "A"]],
            [EDGE_REACHED_NODE],
        )

        result = navigator.navigate((0, 0), (0, 1), HEADING_NORTH)

        self.assertEqual(result, NAV_ARRIVED)
        self.assertEqual(self.motor.calls[:2], [("spin_right", 40, 40), ("brake",)])
        self.assertEqual(navigator.current_heading, HEADING_EAST)


if __name__ == "__main__":
    unittest.main()
