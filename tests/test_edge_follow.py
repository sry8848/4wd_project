import unittest

from src.hardware.line_sensor import LineReading
from src.tasks.edge_follow import (
    EDGE_BLOCKED_ON_PLANNED_EDGE,
    EDGE_CANCELED,
    EDGE_LEAVE_NODE_FAILED,
    EDGE_LINE_LOST,
    EDGE_REACHED_NEXT_NODE,
    EDGE_RECOVERED_TO_START_NODE,
    EDGE_RECOVERY_FAILED,
    EDGE_TIMEOUT,
    EDGE_TURN_FAILED,
    EdgeFollower,
    ObstacleGate,
)
from src.tasks.grid_navigation import HEADING_EAST, HEADING_NORTH, HEADING_WEST
from src.tasks.line_follow import LineFollower


NODE_READING = LineReading(True, True, True, True)
LINE_READING = LineReading(False, True, True, False)
LEFT_READING = LineReading(False, True, False, False)
RIGHT_READING = LineReading(False, False, True, False)
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


class OvershootingClock(FakeClock):
    def monotonic(self):
        value = self.now
        self.now += 0.000001
        return value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds + 0.001


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

    def backward(self, left_speed, right_speed):
        self.calls.append(("backward", left_speed, right_speed))

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
        self.sequence = 0
        self.calls = 0
        self.call_times = []

    def read_snapshot(self):
        self.calls += 1
        self.call_times.append(self.clock.monotonic())
        self.sequence += 1
        if self.obstructed_values:
            obstructed = self.obstructed_values.pop(0)
        else:
            obstructed = False
        return self.sequence, -1.0, obstructed


class FakeReverseRadar:
    def __init__(self):
        self.tick_calls = 0
        self.stop_calls = 0

    def tick(self):
        self.tick_calls += 1

    def stop(self):
        self.stop_calls += 1


class SnapshotObstacleSensor:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.last_snapshot = self.snapshots[-1]

    def read_snapshot(self):
        if self.snapshots:
            self.last_snapshot = self.snapshots.pop(0)
        return self.last_snapshot


class EdgeFollowerTest(unittest.TestCase):
    def test_obstacle_gate_counts_only_distinct_background_readings(self):
        sensor = SnapshotObstacleSensor(
            [
                (4, 30.0, False),
                (5, 12.0, True),
                (5, 12.0, True),
                (6, 11.0, True),
            ]
        )
        gate = ObstacleGate(sensor=sensor, confirm_samples=2)

        gate.start_edge()

        self.assertFalse(gate.check_blocked())
        self.assertFalse(gate.check_blocked())
        self.assertTrue(gate.check_blocked())

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
            left_turn_speed=80,
            right_turn_speed=100,
            search_speed=8,
        )
        self.obstacle_sensor = FakeObstacleSensor(
            obstructed_values or [False],
            self.clock,
        )
        options = {
            "turn_speed": 30,
            "left_turn_rough_seconds": 0.2,
            "right_turn_rough_seconds": 0.2,
            "uturn_rough_seconds": 0.4,
            "leave_node_min_seconds": 0.0,
            "node_clear_samples": 2,
            "node_confirm_samples": 2,
            "node_center_seconds": 0.0,
            "obstacle_confirm_samples": 1,
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
                WHITE_READING,
                WHITE_READING,
                WHITE_READING,
            ],
            obstructed_values=[False, True],
        )

        result = follower.execute_planned_edge(
            HEADING_NORTH,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_BLOCKED_ON_PLANNED_EDGE)
        self.assertEqual(self.motor.calls[0], ("spin_right", 30, 30))
        self.assertEqual(self.obstacle_sensor.calls, 2)
        self.assertGreaterEqual(self.obstacle_sensor.call_times[0], 0.3)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_requires_consecutive_all_white_samples_to_leave(self):
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
                WHITE_READING,
                WHITE_READING,
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

    def test_node_center_sleep_overshoot_is_not_treated_as_cancellation(self):
        clock = OvershootingClock()
        follower = self.build_follower(
            [
                WHITE_READING,
                WHITE_READING,
                NODE_READING,
                NODE_READING,
            ],
            node_center_seconds=0.08,
            time_fn=clock.monotonic,
            sleep_fn=clock.sleep,
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_REACHED_NEXT_NODE)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_node_center_deadline_is_reported_as_timeout_not_cancellation(self):
        follower = self.build_follower(
            [
                WHITE_READING,
                WHITE_READING,
                NODE_READING,
                NODE_READING,
            ],
            node_center_seconds=0.2,
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=0.25,
        )

        self.assertEqual(result.status, EDGE_TIMEOUT)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_reports_line_lost_without_sealing_edge(self):
        follower = self.build_follower(
            [
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
        self.assertGreater(self.obstacle_sensor.calls, 0)
        self.assertIn(("forward", 20, 20), self.motor.calls)
        self.assertNotIn(("spin_left", 8, 8), self.motor.calls)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_stops_for_obstacle_during_all_white_travel(self):
        follower = self.build_follower(
            [WHITE_READING, WHITE_READING, WHITE_READING],
            obstructed_values=[False, True],
            default_reading=WHITE_READING,
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_BLOCKED_ON_PLANNED_EDGE)
        self.assertIn(("forward", 20, 20), self.motor.calls)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_ignores_obstacle_cache_from_before_edge(self):
        follower = self.build_follower(
            [WHITE_READING, WHITE_READING, NODE_READING, NODE_READING],
            obstructed_values=[True, False, False],
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_REACHED_NEXT_NODE)

    def test_execute_planned_edge_cancels_during_rough_turn(self):
        follower = self.build_follower(
            [LINE_READING, LINE_READING],
            right_turn_rough_seconds=0.4,
        )

        result = follower.execute_planned_edge(
            HEADING_NORTH,
            HEADING_EAST,
            max_seconds=3,
            cancel_requested_fn=lambda: self.clock.monotonic() >= 0.1,
        )

        self.assertEqual(result.status, EDGE_CANCELED)
        self.assertLess(self.clock.monotonic(), 0.4)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_cancels_during_edge_travel(self):
        follower = self.build_follower(
            [WHITE_READING, WHITE_READING, WHITE_READING],
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=3,
            cancel_requested_fn=lambda: self.sensor.index >= 3,
        )

        self.assertEqual(result.status, EDGE_CANCELED)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_execute_planned_edge_cancels_during_node_departure(self):
        follower = self.build_follower(
            [WHITE_READING, WHITE_READING],
            node_clear_samples=3,
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_EAST,
            max_seconds=3,
            cancel_requested_fn=lambda: self.sensor.index >= 1,
        )

        self.assertEqual(result.status, EDGE_CANCELED)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_recover_to_start_node_reverses_without_turning_or_ultrasonic(self):
        follower = self.build_follower(
            [WHITE_READING, NODE_READING, NODE_READING],
            obstructed_values=[True, True, True],
            reverse_speed=12,
            reverse_turn_speed=34,
        )

        result = follower.recover_to_start_node(
            return_heading=HEADING_EAST,
            max_seconds=3,
        )

        spin_calls = [
            call for call in self.motor.calls if call[0].startswith("spin_")
        ]
        self.assertEqual(result.status, EDGE_RECOVERED_TO_START_NODE)
        self.assertEqual(result.final_heading, HEADING_EAST)
        self.assertEqual(spin_calls, [])
        self.assertIn(("backward", 12, 12), self.motor.calls)
        self.assertEqual(self.obstacle_sensor.calls, 0)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_reverse_recovery_maps_line_actions_to_backward_motor_commands(self):
        follower = self.build_follower(
            [
                LEFT_READING,
                RIGHT_READING,
                LINE_READING,
                NODE_READING,
                NODE_READING,
            ],
            reverse_speed=11,
            reverse_turn_speed=22,
        )

        result = follower.recover_to_start_node(
            return_heading=HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_RECOVERED_TO_START_NODE)
        self.assertIn(("backward", 22, 0), self.motor.calls)
        self.assertIn(("backward", 0, 22), self.motor.calls)
        self.assertIn(("backward", 11, 11), self.motor.calls)

    def test_reverse_recovery_all_white_drives_straight_until_timeout(self):
        follower = self.build_follower(
            [WHITE_READING, WHITE_READING, WHITE_READING, WHITE_READING],
            default_reading=WHITE_READING,
            line_lost_timeout=0.2,
        )

        result = follower.recover_to_start_node(
            return_heading=HEADING_EAST,
            max_seconds=1,
        )

        self.assertEqual(result.status, EDGE_RECOVERY_FAILED)
        self.assertEqual(result.reason, EDGE_TIMEOUT)
        self.assertIn(("backward", 15, 15), self.motor.calls)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_reverse_recovery_returns_to_straight_after_correction(self):
        follower = self.build_follower(
            [
                RIGHT_READING,
                WHITE_READING,
                LINE_READING,
                NODE_READING,
                NODE_READING,
            ],
            reverse_speed=11,
            reverse_turn_speed=22,
        )

        result = follower.recover_to_start_node(
            return_heading=HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_RECOVERED_TO_START_NODE)
        self.assertIn(("backward", 0, 22), self.motor.calls)
        self.assertIn(("backward", 11, 11), self.motor.calls)
        self.assertNotIn(("backward", 0, 11), self.motor.calls)
        self.assertEqual(self.motor.calls[-1], ("brake",))

    def test_reverse_recovery_ticks_and_stops_reverse_radar(self):
        radar = FakeReverseRadar()
        follower = self.build_follower(
            [LINE_READING, NODE_READING, NODE_READING],
            reverse_radar=radar,
        )

        result = follower.recover_to_start_node(
            return_heading=HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_RECOVERED_TO_START_NODE)
        self.assertGreaterEqual(radar.tick_calls, 1)
        self.assertEqual(radar.stop_calls, 1)

    def test_reverse_recovery_cancellation_stops_reverse_radar(self):
        radar = FakeReverseRadar()
        follower = self.build_follower(
            [LINE_READING, LINE_READING],
            reverse_radar=radar,
        )

        result = follower.recover_to_start_node(
            return_heading=HEADING_EAST,
            max_seconds=3,
            cancel_requested_fn=lambda: self.sensor.index >= 1,
        )

        self.assertEqual(result.status, EDGE_CANCELED)
        self.assertEqual(self.motor.calls[-1], ("brake",))
        self.assertEqual(radar.stop_calls, 1)

    def test_debug_fn_logs_align_leave_and_result_phases(self):
        logs = []
        follower = self.build_follower(
            [
                LINE_READING,
                WHITE_READING,
                WHITE_READING,
                NODE_READING,
                NODE_READING,
            ],
            right_turn_rough_seconds=0.5,
            debug_fn=logs.append,
        )

        result = follower.execute_planned_edge(
            HEADING_NORTH,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_REACHED_NEXT_NODE)
        joined = "\n".join(logs)
        self.assertIn("align turn=right seconds=0.5", joined)
        self.assertIn("turn_acquire success direction=right", joined)
        self.assertIn("leave_node start motion=right_arc speed=20", joined)
        self.assertIn("edge_travel start", joined)
        self.assertIn("edge_exec result status=reached_next_node", joined)
        self.assertIn(("right", 20, 0), self.motor.calls)
        self.assertNotIn(("right", 100, 0), self.motor.calls)

    def test_left_turn_uses_independent_calibrated_duration(self):
        logs = []
        follower = self.build_follower(
            [
                LINE_READING,
                WHITE_READING,
                WHITE_READING,
                NODE_READING,
                NODE_READING,
            ],
            left_turn_rough_seconds=0.6,
            debug_fn=logs.append,
        )

        result = follower.execute_planned_edge(
            HEADING_NORTH,
            HEADING_WEST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_REACHED_NEXT_NODE)
        self.assertIn("align turn=left seconds=0.6", "\n".join(logs))
        self.assertIn(("left", 0, 20), self.motor.calls)
        self.assertNotIn(("left", 0, 80), self.motor.calls)

    def test_uturn_leaves_node_with_low_speed_left_arc(self):
        follower = self.build_follower(
            [
                LINE_READING,
                WHITE_READING,
                WHITE_READING,
                NODE_READING,
                NODE_READING,
            ],
        )

        result = follower.execute_planned_edge(
            HEADING_EAST,
            HEADING_WEST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_REACHED_NEXT_NODE)
        self.assertIn(("spin_left", 30, 30), self.motor.calls)
        self.assertIn(("left", 0, 20), self.motor.calls)
        self.assertNotIn(("left", 0, 80), self.motor.calls)

    def test_right_turn_fine_search_keeps_turning_right_until_line(self):
        follower = self.build_follower(
            [
                NODE_READING,
                WHITE_READING,
                LINE_READING,
                WHITE_READING,
                WHITE_READING,
                WHITE_READING,
                NODE_READING,
                NODE_READING,
            ],
        )

        result = follower.execute_planned_edge(
            HEADING_NORTH,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_REACHED_NEXT_NODE)
        self.assertIn(("spin_right", 8, 8), self.motor.calls)
        self.assertNotIn(("spin_left", 8, 8), self.motor.calls)
        self.assertIn(("right", 20, 0), self.motor.calls)
        self.assertNotIn(("right", 100, 0), self.motor.calls)

    def test_turn_fine_search_timeout_brakes_instead_of_reaching_opposite_line(self):
        follower = self.build_follower(
            [NODE_READING, WHITE_READING, WHITE_READING, WHITE_READING],
            default_reading=WHITE_READING,
            turn_acquire_timeout=0.2,
        )

        result = follower.execute_planned_edge(
            HEADING_NORTH,
            HEADING_EAST,
            max_seconds=3,
        )

        self.assertEqual(result.status, EDGE_TURN_FAILED)
        self.assertEqual(self.motor.calls[-1], ("brake",))


if __name__ == "__main__":
    unittest.main()
