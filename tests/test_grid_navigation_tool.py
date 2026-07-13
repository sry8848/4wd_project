import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from src.tools import test_grid_navigation as tool


class FakeNavigator:
    def __init__(self):
        self.current_node = None
        self.dynamic_blocked_edges = set()
        self.navigate_calls = []

    def navigate(self, start, end, initial_heading):
        self.navigate_calls.append((start, end, initial_heading))
        self.current_node = end
        return "arrived"


class FakeHardware:
    def __init__(self):
        self.navigator = FakeNavigator()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class GridNavigationToolTest(unittest.TestCase):
    def run_tool(self, extra_args=None):
        """运行一次假硬件命令并返回工厂参数和资源对象。"""
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
            *(extra_args or []),
        ]
        hardware = FakeHardware()
        captured = {}

        def fake_factory(grid, **kwargs):
            captured["grid"] = grid
            captured["kwargs"] = kwargs
            return hardware

        output = io.StringIO()
        with patch.object(sys, "argv", args), patch.object(
            tool,
            "create_grid_navigation_hardware",
            side_effect=fake_factory,
        ), redirect_stdout(output):
            tool.main()

        return captured, hardware, output

    def test_no_ultrasonic_is_forwarded_and_hardware_is_closed(self):
        captured, hardware, _output = self.run_tool(["--no-ultrasonic"])

        self.assertFalse(captured["kwargs"]["ultrasonic_enabled"])
        self.assertEqual(hardware.close_calls, 1)
        self.assertEqual(
            hardware.navigator.navigate_calls,
            [((0, 0), (0, 1), "east")],
        )

    def test_confirmed_real_car_defaults_are_forwarded(self):
        captured, _hardware, _output = self.run_tool()
        options = captured["kwargs"]

        self.assertEqual(options["forward_speed"], 20)
        self.assertEqual(options["line_turn_speed"], 80)
        self.assertEqual(options["line_left_turn_speed"], 80)
        self.assertEqual(options["line_right_turn_speed"], 100)
        self.assertEqual(options["search_speed"], 5)
        self.assertEqual(options["spin_speed"], 30)
        self.assertEqual(options["edge_max_seconds"], 20)
        self.assertEqual(options["recovery_max_seconds"], 8)
        self.assertEqual(options["ultrasonic_threshold_cm"], 20)

    def test_ultrasonic_and_edge_parameters_are_forwarded(self):
        captured, _hardware, _output = self.run_tool(
            [
                "--threshold",
                "20",
                "--left-turn-rough-seconds",
                "0.6",
                "--right-turn-rough-seconds",
                "0.5",
                "--uturn-rough-seconds",
                "1.1",
                "--obstacle-confirm-samples",
                "3",
            ]
        )
        options = captured["kwargs"]

        self.assertTrue(options["ultrasonic_enabled"])
        self.assertTrue(options["reverse_radar_enabled"])
        self.assertEqual(options["ultrasonic_threshold_cm"], 20)
        self.assertEqual(options["left_turn_rough_seconds"], 0.6)
        self.assertEqual(options["right_turn_rough_seconds"], 0.5)
        self.assertEqual(options["uturn_rough_seconds"], 1.1)
        self.assertEqual(options["obstacle_confirm_samples"], 3)

    def test_no_reverse_radar_is_forwarded(self):
        captured, _hardware, _output = self.run_tool(["--no-reverse-radar"])

        self.assertFalse(captured["kwargs"]["reverse_radar_enabled"])

    def test_line_turn_speeds_are_forwarded_separately(self):
        captured, _hardware, _output = self.run_tool(
            [
                "--line-turn-speed",
                "70",
                "--line-left-turn-speed",
                "80",
                "--line-right-turn-speed",
                "100",
            ]
        )
        options = captured["kwargs"]

        self.assertEqual(options["line_turn_speed"], 70)
        self.assertEqual(options["line_left_turn_speed"], 80)
        self.assertEqual(options["line_right_turn_speed"], 100)

    def test_reverse_speeds_are_forwarded(self):
        captured, _hardware, _output = self.run_tool(
            ["--reverse-speed", "13", "--reverse-turn-speed", "24"]
        )

        self.assertEqual(captured["kwargs"]["reverse_speed"], 13)
        self.assertEqual(captured["kwargs"]["reverse_turn_speed"], 24)

    def test_line_debug_passes_redirected_stdout(self):
        captured, _hardware, output = self.run_tool(["--line-debug"])

        self.assertIs(captured["kwargs"]["line_debug_output"], output)

    def test_debug_flag_passes_print_callback(self):
        captured, _hardware, _output = self.run_tool(["--debug"])

        self.assertIs(captured["kwargs"]["debug_fn"], print)


if __name__ == "__main__":
    unittest.main()
