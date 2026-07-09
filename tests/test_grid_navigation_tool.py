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
        self.last_distance = 40
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


class FakeBuzzer:
    instances = []

    def __init__(self):
        self.close_calls = 0
        self.instances.append(self)

    def on(self):
        pass

    def off(self):
        pass

    def close(self):
        self.close_calls += 1


class FakeCachedReverseRadar:
    instances = []

    def __init__(self, source, buzzer):
        self.source = source
        self.buzzer = buzzer
        self.stop_calls = 0
        self.instances.append(self)

    def tick(self):
        pass

    def stop(self):
        self.stop_calls += 1


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
        reverse_speed=15,
        reverse_turn_speed=20,
        reverse_radar=None,
        delay_seconds=0.02,
        debug_fn=None,
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
        self.reverse_speed = reverse_speed
        self.reverse_turn_speed = reverse_turn_speed
        self.reverse_radar = reverse_radar
        self.delay_seconds = delay_seconds
        self.debug_fn = debug_fn
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
        debug_fn=None,
        **kwargs,
    ):
        self.current_node = None
        self.dynamic_blocked_edges = set()
        self.debug_fn = debug_fn

    def navigate(self, start, end, initial_heading):
        self.current_node = end
        return "arrived"


class GridNavigationToolTest(unittest.TestCase):
    def setUp(self):
        FakeEdgeFollower.instances = []
        FakeUltrasonicSensor.instances = []
        FakeBuzzer.instances = []
        FakeCachedReverseRadar.instances = []

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
            tool, "Buzzer", FakeBuzzer
        ), patch.object(
            tool, "CachedReverseRadar", FakeCachedReverseRadar
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
        self.assertIs(FakeCachedReverseRadar.instances[0].source, ultrasonic)
        self.assertIs(FakeCachedReverseRadar.instances[0].buzzer, FakeBuzzer.instances[0])
        self.assertIs(
            FakeEdgeFollower.instances[0].reverse_radar,
            FakeCachedReverseRadar.instances[0],
        )
        self.assertEqual(FakeCachedReverseRadar.instances[0].stop_calls, 1)
        self.assertEqual(FakeBuzzer.instances[0].close_calls, 1)

    def test_no_reverse_radar_skips_buzzer_when_ultrasonic_is_enabled(self):
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
            "--no-reverse-radar",
        ]

        with patch.object(sys, "argv", args), patch.object(
            tool, "MotorController", return_value=FakeMotor()
        ), patch.object(tool, "LineSensor", return_value=FakeLineSensor()), patch.object(
            tool, "UltrasonicSensor", FakeUltrasonicSensor
        ), patch.object(
            tool, "Buzzer", FakeBuzzer
        ), patch.object(
            tool, "CachedReverseRadar", FakeCachedReverseRadar
        ), patch.object(
            tool, "EdgeFollower", FakeEdgeFollower
        ), patch.object(
            tool, "GridNavigator", FakeGridNavigator
        ), redirect_stdout(
            io.StringIO()
        ):
            tool.main()

        self.assertEqual(FakeBuzzer.instances, [])
        self.assertEqual(FakeCachedReverseRadar.instances, [])
        self.assertIsNone(FakeEdgeFollower.instances[0].reverse_radar)

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

    def test_reverse_speeds_are_passed_to_edge_follower(self):
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
            "--reverse-speed",
            "13",
            "--reverse-turn-speed",
            "24",
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
            tool.main()

        self.assertEqual(FakeEdgeFollower.instances[0].reverse_speed, 13)
        self.assertEqual(FakeEdgeFollower.instances[0].reverse_turn_speed, 24)

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

    def test_debug_flag_wires_debug_fn_to_edge_follower_and_navigator(self):
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
            "--debug",
        ]
        captured = {}

        class CapturingNavigator(FakeGridNavigator):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                captured["navigator_debug_fn"] = kw.get("debug_fn")

        with patch.object(sys, "argv", args), patch.object(
            tool, "MotorController", return_value=FakeMotor()
        ), patch.object(tool, "LineSensor", return_value=FakeLineSensor()), patch.object(
            tool, "UltrasonicSensor"
        ), patch.object(
            tool, "EdgeFollower", FakeEdgeFollower
        ), patch.object(
            tool, "GridNavigator", CapturingNavigator
        ), redirect_stdout(
            io.StringIO()
        ):
            tool.main()

        self.assertIsNotNone(FakeEdgeFollower.instances[0].debug_fn)
        self.assertIsNotNone(captured["navigator_debug_fn"])
        self.assertIs(FakeEdgeFollower.instances[0].debug_fn, print)
        self.assertIs(captured["navigator_debug_fn"], print)


if __name__ == "__main__":
    unittest.main()
