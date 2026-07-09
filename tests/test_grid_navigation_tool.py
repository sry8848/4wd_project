import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from src.tools import test_grid_navigation as tool


class FakeMotor:
    def brake(self):
        pass

    def close(self):
        pass


class FakeLineSensor:
    def close(self):
        pass


class FakeUltrasonicSensor:
    instances = []

    def __init__(self, threshold_cm=None):
        self.threshold_cm = threshold_cm
        self.obstacle_detected = True
        self.start_monitoring_calls = 0
        self.sync_obstruction_calls = 0
        self.close_calls = 0
        self.instances.append(self)

    def start_monitoring(self):
        self.start_monitoring_calls += 1

    def is_obstructed(self):
        self.sync_obstruction_calls += 1
        raise AssertionError("grid navigation should read cached obstacle state")

    def close(self):
        self.close_calls += 1


class FakeEdgeFollower:
    instances = []

    def __init__(
        self,
        line_follower,
        obstacle_sensor=None,
        turn_speed=30,
        turn_rough_seconds=0.5,
        uturn_rough_seconds=1.2,
        leave_node_min_seconds=0.25,
        node_clear_samples=3,
        node_confirm_samples=3,
        node_center_seconds=0.08,
        obstacle_arm_delay=0.3,
        obstacle_clear_samples=1,
        obstacle_confirm_samples=2,
        line_acquire_timeout=3.0,
        line_lost_timeout=1.0,
        delay_seconds=0.02,
        **kwargs,
    ):
        self.line_follower = line_follower
        self.obstacle_sensor = obstacle_sensor
        self.turn_speed = turn_speed
        self.turn_rough_seconds = turn_rough_seconds
        self.uturn_rough_seconds = uturn_rough_seconds
        self.leave_node_min_seconds = leave_node_min_seconds
        self.node_clear_samples = node_clear_samples
        self.node_confirm_samples = node_confirm_samples
        self.node_center_seconds = node_center_seconds
        self.obstacle_arm_delay = obstacle_arm_delay
        self.obstacle_clear_samples = obstacle_clear_samples
        self.obstacle_confirm_samples = obstacle_confirm_samples
        self.line_acquire_timeout = line_acquire_timeout
        self.line_lost_timeout = line_lost_timeout
        self.delay_seconds = delay_seconds
        self.instances.append(self)


class FakeGridNavigator:
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
        **kwargs,
    ):
        self.current_node = None
        self.dynamic_blocked_edges = set()

    def navigate(self, start, end, initial_heading):
        self.current_node = end
        return "arrived"


class GridNavigationToolTest(unittest.TestCase):
    def setUp(self):
        FakeEdgeFollower.instances = []
        FakeUltrasonicSensor.instances = []

    def test_no_ultrasonic_skips_ultrasonic_sensor_and_passes_none_to_edge_follower(self):
        args = [
            "test_grid_navigation",
            "--rows",
            "3",
            "--cols",
            "5",
            "--start",
            "A1",
            "--end",
            "A2",
            "--heading",
            "east",
            "--no-ultrasonic",
        ]

        with patch.object(sys, "argv", args), patch.object(
            tool, "MotorController", return_value=FakeMotor()
        ), patch.object(tool, "LineSensor", return_value=FakeLineSensor()), patch.object(
            tool, "UltrasonicSensor"
        ) as ultrasonic_cls, patch.object(
            tool, "EdgeFollower", FakeEdgeFollower
        ), patch.object(
            tool, "GridNavigator", FakeGridNavigator
        ), redirect_stdout(
            io.StringIO()
        ):
            try:
                tool.main()
            except SystemExit as exc:
                self.fail(f"--no-ultrasonic should be accepted: {exc}")

        ultrasonic_cls.assert_not_called()
        self.assertIsNone(FakeEdgeFollower.instances[0].obstacle_sensor)

    def test_ultrasonic_mode_uses_background_monitoring_cache_for_obstacle_checks(self):
        args = [
            "test_grid_navigation",
            "--rows",
            "3",
            "--cols",
            "5",
            "--start",
            "A1",
            "--end",
            "A2",
            "--heading",
            "east",
            "--threshold",
            "20",
            "--turn-rough-seconds",
            "0.45",
            "--uturn-rough-seconds",
            "1.1",
            "--obstacle-confirm-samples",
            "3",
        ]

        with patch.object(sys, "argv", args), patch.object(
            tool, "MotorController", return_value=FakeMotor()
        ), patch.object(tool, "LineSensor", return_value=FakeLineSensor()), patch.object(
            tool, "UltrasonicSensor", FakeUltrasonicSensor
        ), patch.object(
            tool, "EdgeFollower", FakeEdgeFollower
        ), patch.object(
            tool, "GridNavigator", FakeGridNavigator
        ), redirect_stdout(
            io.StringIO()
        ):
            tool.main()

        ultrasonic = FakeUltrasonicSensor.instances[0]
        obstacle_sensor = FakeEdgeFollower.instances[0].obstacle_sensor

        self.assertEqual(ultrasonic.threshold_cm, 20)
        self.assertEqual(ultrasonic.start_monitoring_calls, 1)
        self.assertIsNot(obstacle_sensor, ultrasonic)
        self.assertTrue(obstacle_sensor.is_obstructed())
        self.assertEqual(ultrasonic.sync_obstruction_calls, 0)
        self.assertEqual(FakeEdgeFollower.instances[0].turn_rough_seconds, 0.45)
        self.assertEqual(FakeEdgeFollower.instances[0].uturn_rough_seconds, 1.1)
        self.assertEqual(FakeEdgeFollower.instances[0].obstacle_confirm_samples, 3)

    def test_line_turn_speeds_are_passed_separately_to_line_follower(self):
        args = [
            "test_grid_navigation",
            "--rows",
            "3",
            "--cols",
            "5",
            "--start",
            "A1",
            "--end",
            "A2",
            "--heading",
            "east",
            "--line-turn-speed",
            "70",
            "--line-left-turn-speed",
            "80",
            "--line-right-turn-speed",
            "100",
            "--no-ultrasonic",
        ]

        with patch.object(sys, "argv", args), patch.object(
            tool, "MotorController", return_value=FakeMotor()
        ), patch.object(tool, "LineSensor", return_value=FakeLineSensor()), patch.object(
            tool, "EdgeFollower", FakeEdgeFollower
        ), patch.object(
            tool, "GridNavigator", FakeGridNavigator
        ), redirect_stdout(
            io.StringIO()
        ):
            try:
                tool.main()
            except SystemExit as exc:
                self.fail(f"separate line turn speeds should be accepted: {exc}")

        line_follower = FakeEdgeFollower.instances[0].line_follower
        self.assertEqual(line_follower.turn_speed, 70)
        self.assertEqual(line_follower.left_turn_speed, 80)
        self.assertEqual(line_follower.right_turn_speed, 100)

    def test_line_debug_passes_stdout_to_line_follower(self):
        args = [
            "test_grid_navigation",
            "--rows",
            "3",
            "--cols",
            "5",
            "--start",
            "A1",
            "--end",
            "A2",
            "--heading",
            "east",
            "--line-debug",
            "--no-ultrasonic",
        ]
        output = io.StringIO()

        with patch.object(sys, "argv", args), patch.object(
            tool, "MotorController", return_value=FakeMotor()
        ), patch.object(tool, "LineSensor", return_value=FakeLineSensor()), patch.object(
            tool, "EdgeFollower", FakeEdgeFollower
        ), patch.object(
            tool, "GridNavigator", FakeGridNavigator
        ), redirect_stdout(
            output
        ):
            try:
                tool.main()
            except SystemExit as exc:
                self.fail(f"--line-debug should be accepted: {exc}")

        line_follower = FakeEdgeFollower.instances[0].line_follower
        self.assertIs(line_follower.debug_output, output)


if __name__ == "__main__":
    unittest.main()
