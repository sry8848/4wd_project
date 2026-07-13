import unittest
from unittest.mock import Mock, patch

from src.server import hardware_factory


class GridNavigationHardwareTest(unittest.TestCase):
    def test_factory_reuses_existing_navigation_components(self):
        motor = Mock()
        line_sensor = Mock()
        ultrasonic = Mock()
        buzzer = Mock()
        obstacle_sensor = object()
        reverse_radar = Mock()
        line_follower = object()
        edge_follower = object()
        navigator = object()

        with patch.object(
            hardware_factory, "MotorController", return_value=motor
        ), patch.object(
            hardware_factory, "LineSensor", return_value=line_sensor
        ), patch.object(
            hardware_factory, "UltrasonicSensor", return_value=ultrasonic
        ) as ultrasonic_class, patch.object(
            hardware_factory, "Buzzer", return_value=buzzer
        ), patch.object(
            hardware_factory,
            "CachedObstacleSensor",
            return_value=obstacle_sensor,
        ), patch.object(
            hardware_factory,
            "CachedReverseRadar",
            return_value=reverse_radar,
        ), patch.object(
            hardware_factory, "LineFollower", return_value=line_follower
        ) as line_follower_class, patch.object(
            hardware_factory, "EdgeFollower", return_value=edge_follower
        ) as edge_follower_class, patch.object(
            hardware_factory, "GridNavigator", return_value=navigator
        ) as navigator_class:
            resources = hardware_factory.create_grid_navigation_hardware(
                [[1, 1]],
                forward_speed=21,
                ultrasonic_threshold_cm=18,
            )

        ultrasonic_class.assert_called_once_with(threshold_cm=18)
        ultrasonic.start_monitoring.assert_called_once_with()
        line_follower_class.assert_called_once()
        self.assertEqual(line_follower_class.call_args.kwargs["forward_speed"], 21)
        self.assertIs(
            edge_follower_class.call_args.kwargs["obstacle_sensor"],
            obstacle_sensor,
        )
        self.assertIs(
            edge_follower_class.call_args.kwargs["reverse_radar"],
            reverse_radar,
        )
        self.assertEqual(
            edge_follower_class.call_args.kwargs["left_turn_rough_seconds"],
            0.6,
        )
        self.assertEqual(
            edge_follower_class.call_args.kwargs["right_turn_rough_seconds"],
            0.5,
        )
        self.assertEqual(
            line_follower_class.call_args.kwargs["left_turn_speed"],
            80,
        )
        self.assertEqual(
            line_follower_class.call_args.kwargs["right_turn_speed"],
            100,
        )
        self.assertEqual(line_follower_class.call_args.kwargs["search_speed"], 5)
        self.assertEqual(
            navigator_class.call_args.kwargs["edge_max_seconds"],
            20,
        )
        self.assertEqual(
            navigator_class.call_args.kwargs["recovery_max_seconds"],
            8,
        )
        navigator_class.assert_called_once()
        self.assertIs(resources.navigator, navigator)

    def test_factory_skips_optional_hardware_when_ultrasonic_is_disabled(self):
        with patch.object(
            hardware_factory, "MotorController", return_value=Mock()
        ), patch.object(
            hardware_factory, "LineSensor", return_value=Mock()
        ), patch.object(
            hardware_factory, "UltrasonicSensor"
        ) as ultrasonic_class, patch.object(
            hardware_factory, "Buzzer"
        ) as buzzer_class, patch.object(
            hardware_factory, "LineFollower", return_value=object()
        ), patch.object(
            hardware_factory, "EdgeFollower", return_value=object()
        ) as edge_follower_class, patch.object(
            hardware_factory, "GridNavigator", return_value=object()
        ):
            resources = hardware_factory.create_grid_navigation_hardware(
                [[1]],
                ultrasonic_enabled=False,
            )

        ultrasonic_class.assert_not_called()
        buzzer_class.assert_not_called()
        self.assertIsNone(edge_follower_class.call_args.kwargs["obstacle_sensor"])
        self.assertIsNone(resources.ultrasonic)
        self.assertIsNone(resources.reverse_radar)

    def test_close_releases_resources_in_safe_order_once(self):
        events = []
        motor = Mock()
        motor.brake.side_effect = lambda: events.append("motor.brake")
        motor.close.side_effect = lambda: events.append("motor.close")
        line_sensor = Mock()
        line_sensor.close.side_effect = lambda: events.append("line_sensor.close")
        ultrasonic = Mock()
        ultrasonic.close.side_effect = lambda: events.append("ultrasonic.close")
        buzzer = Mock()
        buzzer.close.side_effect = lambda: events.append("buzzer.close")
        reverse_radar = Mock()
        reverse_radar.stop.side_effect = lambda: events.append("reverse_radar.stop")
        resources = hardware_factory.GridNavigationHardware(
            navigator=object(),
            motor=motor,
            line_sensor=line_sensor,
            ultrasonic=ultrasonic,
            buzzer=buzzer,
            reverse_radar=reverse_radar,
        )

        resources.close()
        resources.close()

        self.assertEqual(
            events,
            [
                "motor.brake",
                "reverse_radar.stop",
                "buzzer.close",
                "ultrasonic.close",
                "line_sensor.close",
                "motor.close",
            ],
        )


if __name__ == "__main__":
    unittest.main()
