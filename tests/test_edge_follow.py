import unittest

from src.hardware.line_sensor import LineReading
from src.tasks.edge_follow import (
    EDGE_BLOCKED_BEFORE_ENTERING,
    EDGE_BLOCKED_MID_EDGE,
    EDGE_REACHED_NODE,
    EDGE_RECOVERED,
    EDGE_RECOVERY_FAILED,
    EDGE_TIMEOUT,
    EdgeFollower,
)
from src.tasks.line_follow import ACTION_FORWARD, ACTION_NODE


NODE_READING = LineReading(True, True, True, True)
LINE_READING = LineReading(False, True, True, False)


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
    def __init__(self, readings):
        self.readings = list(readings)

    def read(self):
        if self.readings:
            return self.readings.pop(0)
        return LINE_READING


class FakeMotor:
    def __init__(self):
        self.calls = []

    def forward(self, left_speed, right_speed):
        self.calls.append(("forward", left_speed, right_speed))

    def spin_left(self, left_speed, right_speed):
        self.calls.append(("spin_left", left_speed, right_speed))

    def brake(self):
        self.calls.append(("brake",))


class FakeLineFollower:
    def __init__(self, sensor, motor, actions=None, run_results=None):
        self.sensor = sensor
        self.motor = motor
        self.forward_speed = 20
        self.actions = list(actions or [])
        self.run_results = list(run_results or [])
        self.step_calls = 0
        self.run_track_calls = []

    def step(self):
        self.step_calls += 1
        if self.actions:
            action = self.actions.pop(0)
        else:
            action = ACTION_FORWARD
        if action == ACTION_NODE:
            self.motor.brake()
        return action

    def run_track(self, max_seconds, delay_seconds=0.02):
        self.run_track_calls.append((max_seconds, delay_seconds))
        if self.run_results:
            return self.run_results.pop(0)
        return False


class FakeObstacleSensor:
    def __init__(self, obstructed_values):
        self.obstructed_values = list(obstructed_values)
        self.calls = 0

    def is_obstructed(self):
        self.calls += 1
        if self.obstructed_values:
            return self.obstructed_values.pop(0)
        return False


class EdgeFollowerTest(unittest.TestCase):
    def build_follower(self, readings, actions=None, obstructed_values=None, run_results=None):
        self.clock = FakeClock()
        self.motor = FakeMotor()
        self.sensor = FakeSensor(readings)
        self.line_follower = FakeLineFollower(
            self.sensor,
            self.motor,
            actions=actions,
            run_results=run_results,
        )
        self.obstacle_sensor = FakeObstacleSensor(obstructed_values or [False])
        return EdgeFollower(
            self.line_follower,
            obstacle_sensor=self.obstacle_sensor,
            turn_speed=30,
            uturn_seconds=0.5,
            delay_seconds=0.1,
            time_fn=self.clock.monotonic,
            sleep_fn=self.clock.sleep,
        )

    def test_follow_edge_does_not_enter_edge_when_obstacle_is_seen_first(self):
        follower = self.build_follower(
            [NODE_READING],
            actions=[ACTION_FORWARD],
            obstructed_values=[True],
        )

        result = follower.follow_edge(max_seconds=1)

        self.assertEqual(result, EDGE_BLOCKED_BEFORE_ENTERING)
        self.assertEqual(self.line_follower.step_calls, 0)
        self.assertEqual(self.motor.calls, [("brake",)])

    def test_follow_edge_leaves_current_node_before_accepting_next_node(self):
        follower = self.build_follower(
            [NODE_READING, LINE_READING],
            actions=[ACTION_FORWARD, ACTION_NODE],
            obstructed_values=[False, False, False],
        )

        result = follower.follow_edge(max_seconds=1)

        self.assertEqual(result, EDGE_REACHED_NODE)
        self.assertEqual(self.motor.calls[0], ("forward", 20, 20))
        self.assertEqual(self.line_follower.step_calls, 2)

    def test_follow_edge_brakes_when_obstacle_appears_mid_edge(self):
        follower = self.build_follower(
            [LINE_READING],
            actions=[ACTION_FORWARD],
            obstructed_values=[False, False, True],
        )

        result = follower.follow_edge(max_seconds=1)

        self.assertEqual(result, EDGE_BLOCKED_MID_EDGE)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_follow_edge_times_out_when_next_node_is_not_reached(self):
        follower = self.build_follower(
            [LINE_READING],
            actions=[ACTION_FORWARD, ACTION_FORWARD, ACTION_FORWARD],
            obstructed_values=[False, False, False, False, False],
        )

        result = follower.follow_edge(max_seconds=0.25)

        self.assertEqual(result, EDGE_TIMEOUT)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_recover_to_start_node_turns_around_runs_track_and_turns_back(self):
        follower = self.build_follower(
            [LINE_READING],
            run_results=[True],
        )

        result = follower.recover_to_start_node(max_seconds=2)

        self.assertEqual(result, EDGE_RECOVERED)
        self.assertEqual(
            self.motor.calls,
            [
                ("spin_left", 30, 30),
                ("brake",),
                ("spin_left", 30, 30),
                ("brake",),
                ("brake",),
            ],
        )
        self.assertEqual(self.line_follower.run_track_calls, [(2, 0.1)])

    def test_recover_to_start_node_reports_failure_when_track_back_fails(self):
        follower = self.build_follower(
            [LINE_READING],
            run_results=[False],
        )

        result = follower.recover_to_start_node(max_seconds=2)

        self.assertEqual(result, EDGE_RECOVERY_FAILED)
        self.assertEqual(self.motor.calls[-1], ("brake",))


if __name__ == "__main__":
    unittest.main()
