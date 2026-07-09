import unittest

from src.hardware.line_sensor import LineReading
from src.tasks.edge_follow import (
    EDGE_BLOCKED_ON_PLANNED_EDGE,
    EDGE_LEAVE_NODE_FAILED,
    EDGE_LINE_LOST,
    EDGE_REACHED_NEXT_NODE,
    EDGE_RECOVERED_TO_START_NODE,
    EdgeFollower,
)
from src.tasks.grid_navigation import HEADING_EAST, HEADING_NORTH, HEADING_WEST
from src.tasks.line_follow import LineFollower


NODE_READING = LineReading(True, True, True, True)
LINE_READING = LineReading(False, True, True, False)
WHITE_READING = LineReading(False, False, False, False)


class FakeClock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeSensor:
    def __init__(self, readings, default=LINE_READING):
        self.readings = list(readings)
        self.default = default
        self.index = 0

    def read(self):
        self.index += 1
        if self.readings:
            return self.readings.pop(0)
        return self.default


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

    def spin_right(self, left_speed, right_speed):
        self.calls.append(("spin_right", left_speed, right_speed))

    def brake(self):
        self.calls.append(("brake",))


class FakeObstacleSensor:
    def __init__(self, obstructed_values, clock):
        self.obstructed_values = list(obstructed_values)
        self.clock = clock
        self.calls = 0
        self.call_times = []

    def is_obstructed(self):
        self.calls += 1
        self.call_times.append(self.clock.monotonic())
        if self.obstructed_values:
            return self.obstructed_values.pop(0)
        return False


class EdgeFollowerTest(unittest.TestCase):
    def build_follower(
        self,
        readings,
        obstructed_values=None,
        default_reading=LINE_READING,
        **kwargs,
    ):
        self.clock = FakeClock()
        self.motor = FakeMotor()
        self.sensor = FakeSensor(readings, default=default_reading)
        self.line_follower = LineFollower(
            self.sensor,
            self.motor,
            forward_speed=20,
            turn_speed=70,
            search_speed=8,
        )
        self.obstacle_sensor = FakeObstacleSensor(
            obstructed_values or [False],
            self.clock,
        )
        options = {
            "turn_speed": 30,
            "turn_rough_seconds": 0.2,
            "uturn_rough_seconds": 0.4,
            "leave_node_min_seconds": 0.0,
            "node_clear_samples": 2,
            "node_confirm_samples": 2,
            "node_center_seconds": 0.0,
            "obstacle_arm_delay": 0.0,
            "obstacle_clear_samples": 1,
            "obstacle_confirm_samples": 2,
            "line_acquire_timeout": 0.5,
            "line_lost_timeout": 0.3,
            "delay_seconds": 0.1,
            "time_fn": self.clock.monotonic,
            "sleep_fn": self.clock.sleep,
        }
        options.update(kwargs)
        return EdgeFollower(
            self.line_follower,
            obstacle_sensor=self.obstacle_sensor,
            **options,
        )

    def test_execute_planned_edge_reads_ultrasonic_only_after_leaving_node(self):
        follower = self.build_follower(
            [
                NODE_READING,
                LINE_READING,
                LINE_READING,
                LINE_READING,
                LINE_READING,
                LINE_READING,
            ],
            obstructed_values=[False, True, True],
        )

        result = follower.execute_planned_edge(
            HEADING_NORTH,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_BLOCKED_ON_PLANNED_EDGE)
        self.assertEqual(self.motor.calls[0], ("spin_right", 30, 30))
        self.assertEqual(self.obstacle_sensor.calls, 3)
        self.assertGreaterEqual(self.obstacle_sensor.call_times[0], 0.3)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_requires_consecutive_non_node_samples_to_leave(self):
        follower = self.build_follower(
            [NODE_READING, LINE_READING],
            default_reading=NODE_READING,
            line_acquire_timeout=0.25,
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=1,
        )

        self.assertEqual(result.status, EDGE_LEAVE_NODE_FAILED)
        self.assertEqual(self.obstacle_sensor.calls, 0)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_requires_consecutive_node_samples_to_arrive(self):
        follower = self.build_follower(
            [
                LINE_READING,
                LINE_READING,
                NODE_READING,
                LINE_READING,
                NODE_READING,
                NODE_READING,
            ],
            obstructed_values=[False, False, False, False],
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_REACHED_NEXT_NODE)
        self.assertEqual(self.sensor.index, 6)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_reports_line_lost_without_sealing_edge(self):
        follower = self.build_follower(
            [
                LINE_READING,
                LINE_READING,
                WHITE_READING,
                WHITE_READING,
                WHITE_READING,
                WHITE_READING,
                WHITE_READING,
            ],
            default_reading=WHITE_READING,
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_LINE_LOST)
        self.assertEqual(self.obstacle_sensor.calls, 0)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_recover_to_start_node_turns_once_and_does_not_read_ultrasonic(self):
        follower = self.build_follower(
            [LINE_READING, NODE_READING, NODE_READING],
            obstructed_values=[True, True, True],
        )

        result = follower.recover_to_start_node(
            return_heading=HEADING_WEST,
            max_seconds=3,
        )

        spin_left_calls = [
            call for call in self.motor.calls if call[0] == "spin_left"
        ]
        self.assertEqual(result.status, EDGE_RECOVERED_TO_START_NODE)
        self.assertEqual(result.final_heading, HEADING_WEST)
        self.assertEqual(len(spin_left_calls), 1)
        self.assertEqual(self.obstacle_sensor.calls, 0)
        self.assertEqual(self.motor.calls[-1], ("brake",))


if __name__ == "__main__":
    unittest.main()
