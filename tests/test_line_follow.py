import unittest

from src.hardware.line_sensor import LineReading
from src.tasks.line_follow import (
    ACTION_FORWARD,
    ACTION_LEFT,
    ACTION_NODE,
    ACTION_RIGHT,
    ACTION_SEARCH_LEFT,
    LineFollower,
    decide_line_action,
    is_at_node,
    track_node_check,
)


class FakeSensor:
    def __init__(self, readings):
        self.readings = list(readings)

    def read(self):
        if self.readings:
            return self.readings.pop(0)
        return LineReading(False, False, False, False)


class FakeMotor:
    def __init__(self):
        self.calls = []

    def forward(self, left_speed, right_speed):
        self.calls.append(("forward", left_speed, right_speed))

    def left(self, left_speed, right_speed):
        self.calls.append(("left", left_speed, right_speed))

    def right(self, left_speed, right_speed):
        self.calls.append(("right", left_speed, right_speed))

    def spin_left(self, left_speed, right_speed):
        self.calls.append(("spin_left", left_speed, right_speed))

    def brake(self):
        self.calls.append(("brake",))


class NodeDetectionTest(unittest.TestCase):
    def test_all_four_sensors_on_black_is_node(self):
        self.assertTrue(is_at_node(LineReading(True, True, True, True)))

    def test_inner_sensors_and_one_outer_sensor_on_black_is_node(self):
        self.assertTrue(is_at_node(LineReading(True, True, True, False)))
        self.assertTrue(is_at_node(LineReading(False, True, True, True)))

    def test_only_inner_sensors_on_black_is_line_not_node(self):
        self.assertFalse(is_at_node(LineReading(False, True, True, False)))

    def test_track_node_check_reads_sensor_once_and_returns_node_result(self):
        sensor = FakeSensor([LineReading(True, True, True, False)])

        self.assertTrue(track_node_check(sensor))


class LineDecisionTest(unittest.TestCase):
    def test_decides_forward_when_two_inner_sensors_are_on_line(self):
        action = decide_line_action(LineReading(False, True, True, False))

        self.assertEqual(action, ACTION_FORWARD)

    def test_decides_left_when_line_drifts_to_left_sensors(self):
        action = decide_line_action(LineReading(False, True, False, False))

        self.assertEqual(action, ACTION_LEFT)

    def test_decides_right_when_line_drifts_to_right_sensors(self):
        action = decide_line_action(LineReading(False, False, True, False))

        self.assertEqual(action, ACTION_RIGHT)

    def test_decides_search_left_when_no_sensor_sees_line(self):
        action = decide_line_action(LineReading(False, False, False, False))

        self.assertEqual(action, ACTION_SEARCH_LEFT)

    def test_node_has_priority_over_turn_decisions(self):
        action = decide_line_action(LineReading(True, True, True, True))

        self.assertEqual(action, ACTION_NODE)


class LineFollowerTest(unittest.TestCase):
    def test_step_reads_sensor_and_applies_forward_action(self):
        sensor = FakeSensor([LineReading(False, True, True, False)])
        motor = FakeMotor()
        follower = LineFollower(sensor, motor, forward_speed=20, turn_speed=70, search_speed=8)

        action = follower.step()

        self.assertEqual(action, ACTION_FORWARD)
        self.assertEqual(motor.calls, [("forward", 20, 20)])

    def test_step_brakes_when_node_is_detected(self):
        sensor = FakeSensor([LineReading(True, True, True, True)])
        motor = FakeMotor()
        follower = LineFollower(sensor, motor)

        action = follower.step()

        self.assertEqual(action, ACTION_NODE)
        self.assertEqual(motor.calls, [("brake",)])

    def test_run_track_brakes_and_returns_true_after_reaching_node(self):
        sensor = FakeSensor(
            [
                LineReading(False, True, False, False),
                LineReading(False, True, True, False),
                LineReading(True, True, True, True),
            ]
        )
        motor = FakeMotor()
        follower = LineFollower(sensor, motor, forward_speed=20, turn_speed=70, search_speed=8)

        reached_node = follower.run_track(max_seconds=1, delay_seconds=0)

        self.assertTrue(reached_node)
        self.assertEqual(
            motor.calls,
            [
                ("left", 0, 70),
                ("forward", 20, 20),
                ("brake",),
            ],
        )

    def test_run_track_rejects_non_positive_timeout(self):
        sensor = FakeSensor([])
        motor = FakeMotor()
        follower = LineFollower(sensor, motor)

        with self.assertRaises(ValueError):
            follower.run_track(max_seconds=0)


if __name__ == "__main__":
    unittest.main()
