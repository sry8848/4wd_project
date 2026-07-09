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
        uturn_seconds=1.2,
        delay_seconds=0.02,
    ):
        self.line_follower = line_follower
        self.obstacle_sensor = obstacle_sensor
        self.turn_speed = turn_speed
        self.uturn_seconds = uturn_seconds
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


if __name__ == "__main__":
    unittest.main()
