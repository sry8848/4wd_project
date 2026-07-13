"""Execute one planned grid edge with protected line following.

The edge executor does not know the map and does not run A*. It only tries to
leave the current trusted node, travel along the planned edge, report a blocked
edge when the ultrasonic gate confirms one, or recover back to the start node.
"""

from dataclasses import dataclass
import time
from typing import Optional

from src.tasks.line_follow import (
    ACTION_FORWARD,
    ACTION_LEFT,
    ACTION_NODE,
    ACTION_RIGHT,
    LineStepResult,
    decide_line_action,
    is_at_node,
    is_centered_line,
    is_line_seen,
)


EDGE_REACHED_NEXT_NODE = "reached_next_node"
EDGE_BLOCKED_ON_PLANNED_EDGE = "blocked_on_planned_edge"
EDGE_RECOVERED_TO_START_NODE = "recovered_to_start_node"
EDGE_TURN_FAILED = "turn_failed"
EDGE_LEAVE_NODE_FAILED = "leave_node_failed"
EDGE_LINE_LOST = "line_lost"
EDGE_TIMEOUT = "timeout"
EDGE_RECOVERY_FAILED = "recovery_failed"
EDGE_CANCELED = "canceled"

_CANCEL_POLL_SECONDS = 0.02

# Backward-compatible names for older callers/tests. New code should use the
# explicit state names above.
EDGE_REACHED_NODE = EDGE_REACHED_NEXT_NODE
EDGE_BLOCKED_MID_EDGE = EDGE_BLOCKED_ON_PLANNED_EDGE
EDGE_BLOCKED_BEFORE_ENTERING = "blocked_before_entering"
EDGE_RECOVERED = EDGE_RECOVERED_TO_START_NODE

_HEADINGS = ("north", "east", "south", "west")


@dataclass(frozen=True)
class EdgeExecutionResult:
    """Structured result returned by a planned edge or recovery execution.

    Parameters:
    status: One of the EDGE_* status strings defined in this module.
    final_heading: Heading after the action finishes when it is known.
    reason: Optional low-level reason for a failure status.
    """

    status: str
    final_heading: Optional[str] = None
    reason: Optional[str] = None


class CachedObstacleSensor:
    """Expose atomic background ultrasonic readings to the edge follower.

    Parameters:
    source: Object providing get_cached_reading().
    """

    def __init__(self, source):
        self.source = source

    def read_snapshot(self):
        """Return ``(sequence, distance_cm, obstructed)`` without measuring."""
        sequence, distance, obstructed = self.source.get_cached_reading()
        return sequence, distance, bool(obstructed)


class ObstacleGate:
    """Accept only fresh ultrasonic readings for the current planned edge.

    Parameters:
    sensor: Optional object providing read_snapshot().
    confirm_samples: Consecutive fresh obstacle readings required to block the edge.
    """

    def __init__(
        self,
        sensor=None,
        confirm_samples=1,
    ):
        if confirm_samples <= 0:
            raise ValueError("confirm_samples must be > 0")

        self.sensor = sensor
        self.confirm_samples = confirm_samples
        self.last_sequence = None
        self.hit_count = 0

    def start_edge(self):
        """Ignore cache published before the current EDGE_TRAVEL phase."""
        self.last_sequence = None
        self.hit_count = 0
        if self.sensor is not None:
            self.last_sequence = self.sensor.read_snapshot()[0]

    def check_blocked(self):
        """Return True after confirmed new readings report an obstacle."""
        if self.sensor is None or self.last_sequence is None:
            return False

        sequence, _distance, obstructed = self.sensor.read_snapshot()
        if sequence <= self.last_sequence:
            return False
        self.last_sequence = sequence

        if not obstructed:
            self.hit_count = 0
            return False

        self.hit_count += 1
        return self.hit_count >= self.confirm_samples


class EdgeFollower:
    """Execute one planned edge from the current trusted node.

    Parameters:
    line_follower: LineFollower-like object with step(), apply_reading(), sensor,
        motor, and speed attributes.
    obstacle_sensor: Optional ultrasonic cache wrapper used only in EDGE_TRAVEL.
    turn_speed: PWM speed used by coarse turns.
    left_turn_rough_seconds: Deliberately short left pre-turn duration.
    right_turn_rough_seconds: Deliberately short right pre-turn duration.
    uturn_rough_seconds: Deliberately short left-spin U-turn duration.
    turn_acquire_timeout: Maximum directional fine-search time after a pre-turn.
    leave_node_min_seconds: Minimum protected time before leaving can succeed.
    node_clear_samples: Consecutive non-node line samples required to leave.
    node_confirm_samples: Node samples required to enter a node; default 1 means
        one matching reading is accepted immediately.
    node_center_seconds: Short forward push after confirming a node.
    obstacle_confirm_samples: Fresh filtered obstacle readings required before
        blocking an edge.
    line_acquire_timeout: Maximum protected leave/search time.
    line_lost_timeout: Maximum all-white line loss time during travel.
    reverse_speed: PWM speed used when backing straight along the current edge.
    reverse_turn_speed: PWM speed used for reverse line corrections.
    reverse_radar: Optional non-blocking reverse-radar beeper with tick()/stop().
    delay_seconds: Loop delay between sensor samples.
    debug_fn: Optional callback(message) for field-test phase logs.
    time_fn/sleep_fn: Injectable time functions for deterministic tests.
    """

    def __init__(
        self,
        line_follower,
        obstacle_sensor=None,
        turn_speed=30,
        left_turn_rough_seconds=0.4,
        right_turn_rough_seconds=0.3,
        uturn_rough_seconds=0.8,
        turn_acquire_timeout=5.0,
        leave_node_min_seconds=0.25,
        node_clear_samples=3,
        node_confirm_samples=1,
        node_center_seconds=0.08,
        obstacle_confirm_samples=1,
        line_acquire_timeout=3.0,
        line_lost_timeout=5.0,
        reverse_speed=15,
        reverse_turn_speed=20,
        reverse_radar=None,
        delay_seconds=0.02,
        debug_fn=None,
        time_fn=None,
        sleep_fn=None,
    ):
        if (
            left_turn_rough_seconds < 0
            or right_turn_rough_seconds < 0
            or uturn_rough_seconds < 0
        ):
            raise ValueError("rough turn seconds must be >= 0")
        if turn_acquire_timeout <= 0:
            raise ValueError("turn_acquire_timeout must be > 0")
        if leave_node_min_seconds < 0:
            raise ValueError("leave_node_min_seconds must be >= 0")
        if node_clear_samples <= 0:
            raise ValueError("node_clear_samples must be > 0")
        if node_confirm_samples <= 0:
            raise ValueError("node_confirm_samples must be > 0")
        if node_center_seconds < 0:
            raise ValueError("node_center_seconds must be >= 0")
        if line_acquire_timeout <= 0:
            raise ValueError("line_acquire_timeout must be > 0")
        if line_lost_timeout <= 0:
            raise ValueError("line_lost_timeout must be > 0")
        if reverse_speed < 0 or reverse_speed > 100:
            raise ValueError("reverse_speed must be between 0 and 100")
        if reverse_turn_speed < 0 or reverse_turn_speed > 100:
            raise ValueError("reverse_turn_speed must be between 0 and 100")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be >= 0")

        self.line_follower = line_follower
        self.motor = line_follower.motor
        self.obstacle_sensor = obstacle_sensor
        self.turn_speed = turn_speed
        self.left_turn_rough_seconds = left_turn_rough_seconds
        self.right_turn_rough_seconds = right_turn_rough_seconds
        self.uturn_rough_seconds = uturn_rough_seconds
        self.turn_acquire_timeout = turn_acquire_timeout
        self.leave_node_min_seconds = leave_node_min_seconds
        self.node_clear_samples = node_clear_samples
        self.node_confirm_samples = node_confirm_samples
        self.node_center_seconds = node_center_seconds
        self.line_acquire_timeout = line_acquire_timeout
        self.line_lost_timeout = line_lost_timeout
        self.reverse_speed = reverse_speed
        self.reverse_turn_speed = reverse_turn_speed
        self.reverse_radar = reverse_radar
        self.delay_seconds = delay_seconds
        self._debug = debug_fn
        self._time = time_fn if time_fn is not None else time.monotonic
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self.obstacle_gate = ObstacleGate(
            sensor=obstacle_sensor,
            confirm_samples=obstacle_confirm_samples,
        )

    def _log(self, message):
        """Emit one debug line when a debug callback is configured."""
        if self._debug is not None:
            self._debug(message)

    def execute_planned_edge(
        self,
        current_heading,
        target_heading,
        max_seconds,
        cancel_requested_fn=None,
    ):
        """Align to target_heading, leave the node, then travel the edge.

        Parameters:
        current_heading: Current trusted heading, or None to skip coarse align.
        target_heading: Heading of the planned edge, or None to keep heading.
        max_seconds: Whole-edge timeout including turn, leave, and travel.
        cancel_requested_fn: Optional callback returning True when motion must stop.

        Steps:
        Check cancellation before and during align, node departure, and edge travel.
        Every cancellation path brakes before returning EDGE_CANCELED.
        """
        if max_seconds <= 0:
            raise ValueError("max_seconds must be > 0")
        if self._cancel_requested(cancel_requested_fn):
            return EdgeExecutionResult(EDGE_CANCELED)

        deadline = self._time() + max_seconds
        self._log(
            f"edge_exec start current={current_heading} target={target_heading} "
            f"max_seconds={max_seconds}"
        )
        aligned, turn_search_left = self._align_to_heading(
            current_heading,
            target_heading,
            deadline,
            cancel_requested_fn,
        )
        if not aligned:
            if self._cancel_requested(cancel_requested_fn):
                return EdgeExecutionResult(EDGE_CANCELED)
            self.motor.brake()
            result = EdgeExecutionResult(EDGE_TURN_FAILED, reason=EDGE_TIMEOUT)
            self._log(f"edge_exec result status={result.status} reason={result.reason}")
            return result

        if not self._leave_node(
            deadline,
            cancel_requested_fn,
            search_left=turn_search_left,
        ):
            if self._cancel_requested(cancel_requested_fn):
                return EdgeExecutionResult(EDGE_CANCELED)
            self.motor.brake()
            result = EdgeExecutionResult(EDGE_LEAVE_NODE_FAILED, reason=EDGE_TIMEOUT)
            self._log(f"edge_exec result status={result.status} reason={result.reason}")
            return result

        result = self._travel_edge(
            deadline,
            final_heading=target_heading,
            cancel_requested_fn=cancel_requested_fn,
        )
        self._log(
            f"edge_exec result status={result.status} "
            f"reason={result.reason} final_heading={result.final_heading}"
        )
        return result

    def follow_edge(self, max_seconds):
        """Legacy wrapper that executes the current heading without alignment.

        Parameters:
        max_seconds: Whole-edge timeout. New callers should use
            execute_planned_edge().
        """
        return self.execute_planned_edge(None, None, max_seconds).status

    def recover_to_start_node(
        self,
        return_heading=None,
        max_seconds=None,
        cancel_requested_fn=None,
    ):
        """Reverse along the current edge back to the start node.

        Parameters:
        return_heading: Heading after recovery, normally the planned edge heading.
            For backward compatibility, a numeric first argument is treated as
            max_seconds.
        max_seconds: Recovery timeout.
        cancel_requested_fn: Optional callback returning True when motion must stop.

        Steps:
        Check cancellation before and during reverse recovery, brake on cancel, and
        always stop the reverse radar before returning.
        """
        if max_seconds is None and isinstance(return_heading, (int, float)):
            max_seconds = return_heading
            return_heading = None
        if max_seconds is None or max_seconds <= 0:
            raise ValueError("max_seconds must be > 0")

        deadline = self._time() + max_seconds
        self._log(
            f"recovery start return_heading={return_heading} max_seconds={max_seconds}"
        )
        try:
            if self._cancel_requested(cancel_requested_fn):
                return EdgeExecutionResult(
                    EDGE_CANCELED,
                    final_heading=return_heading,
                )
            result = self._reverse_to_node_without_obstacle(
                deadline,
                final_heading=return_heading,
                cancel_requested_fn=cancel_requested_fn,
            )
            if result.status == EDGE_CANCELED:
                return result
            if result.status == EDGE_RECOVERED_TO_START_NODE:
                self._log(
                    f"recovery result status={result.status} "
                    f"final_heading={result.final_heading}"
                )
                return result

            self.motor.brake()
            failed = EdgeExecutionResult(
                EDGE_RECOVERY_FAILED,
                final_heading=return_heading,
                reason=result.status,
            )
            self._log(f"recovery result status={failed.status} reason={failed.reason}")
            return failed
        finally:
            if self.reverse_radar is not None:
                self.reverse_radar.stop()

    def _align_to_heading(
        self,
        current_heading,
        target_heading,
        deadline,
        cancel_requested_fn,
    ):
        # Step 1: Deliberate under-turn, then directional sensor acquisition.
        if self._cancel_requested(cancel_requested_fn):
            return False, None
        if current_heading is None or target_heading is None:
            self._log("align skip (heading unknown)")
            return self._time() < deadline, None
        if current_heading not in _HEADINGS or target_heading not in _HEADINGS:
            raise ValueError("heading must be north/east/south/west")

        current_index = _HEADINGS.index(current_heading)
        target_index = _HEADINGS.index(target_heading)
        diff = (target_index - current_index) % len(_HEADINGS)

        if diff == 0:
            self._log(f"align skip already_facing={target_heading}")
            return self._time() < deadline, None
        if diff == 1:
            self._log(
                f"align turn=right seconds={self.right_turn_rough_seconds} "
                f"from={current_heading} to={target_heading}"
            )
            return self._turn_and_acquire(
                left=False,
                seconds=self.right_turn_rough_seconds,
                deadline=deadline,
                cancel_requested_fn=cancel_requested_fn,
            ), False
        if diff == 2:
            self._log(
                f"align turn=uturn_left seconds={self.uturn_rough_seconds} "
                f"from={current_heading} to={target_heading}"
            )
            return self._turn_and_acquire(
                left=True,
                seconds=self.uturn_rough_seconds,
                deadline=deadline,
                cancel_requested_fn=cancel_requested_fn,
            ), True
        self._log(
            f"align turn=left seconds={self.left_turn_rough_seconds} "
            f"from={current_heading} to={target_heading}"
        )
        return self._turn_and_acquire(
            left=True,
            seconds=self.left_turn_rough_seconds,
            deadline=deadline,
            cancel_requested_fn=cancel_requested_fn,
        ), True

    def _turn_and_acquire(self, left, seconds, deadline, cancel_requested_fn):
        """Run one bounded pre-turn and acquire the next line in that direction.

        Parameters:
        left: True for left rotation, False for right rotation.
        seconds: Open-loop pre-turn duration, deliberately shorter than the target.
        deadline: Absolute deadline of the whole edge operation.
        cancel_requested_fn: Optional callback returning True when motion must stop.
        """
        if not self._rough_turn(left, seconds, deadline, cancel_requested_fn):
            return False
        return self._acquire_turn_line(left, deadline, cancel_requested_fn)

    def _rough_turn(self, left, seconds, deadline, cancel_requested_fn):
        if self._time() >= deadline or self._cancel_requested(cancel_requested_fn):
            return False
        if seconds > 0:
            if left:
                self.motor.spin_left(self.turn_speed, self.turn_speed)
            else:
                self.motor.spin_right(self.turn_speed, self.turn_speed)
            if not self._wait_while_active(
                seconds,
                deadline,
                cancel_requested_fn,
            ):
                return False
        self.motor.brake()
        return self._time() < deadline

    def _acquire_turn_line(self, left, deadline, cancel_requested_fn):
        """Fine-turn in the planned direction until the target line is acquired.

        Parameters:
        left: True to search left, False to search right.
        deadline: Absolute deadline of the whole edge operation.
        cancel_requested_fn: Optional callback returning True when motion must stop.

        Steps:
        Accept a centered ordinary line immediately. Otherwise ignore the old node,
        wait until the sensors clear it, and stop on the first line seen afterward.
        """
        started_at = self._time()
        finish_at = min(started_at + self.turn_acquire_timeout, deadline)
        cleared_old_line = False
        direction = "left" if left else "right"
        last_summary = None
        self._log(
            f"turn_acquire start direction={direction} "
            f"max_seconds={self.turn_acquire_timeout}"
        )

        while self._time() < finish_at:
            if self._cancel_requested(cancel_requested_fn):
                return False

            reading = self.line_follower.sensor.read()
            line_seen = is_line_seen(reading)
            node_seen = is_at_node(reading)
            centered = is_centered_line(reading)
            action = decide_line_action(reading)
            result = LineStepResult(reading, action, node_seen, line_seen, centered)
            summary = _reading_summary(result)
            if summary != last_summary:
                self._log(f"turn_acquire {summary} cleared={int(cleared_old_line)}")
                last_summary = summary

            if (centered and not node_seen) or (cleared_old_line and line_seen):
                self.motor.brake()
                elapsed = self._time() - started_at
                self._log(
                    f"turn_acquire success direction={direction} elapsed={elapsed:.3f}"
                )
                return True

            if not line_seen:
                cleared_old_line = True

            if left:
                self.motor.spin_left(
                    self.line_follower.search_speed,
                    self.line_follower.search_speed,
                )
            else:
                self.motor.spin_right(
                    self.line_follower.search_speed,
                    self.line_follower.search_speed,
                )
            self._sleep(self.delay_seconds)

        self.motor.brake()
        self._log(
            f"turn_acquire failed direction={direction} last={last_summary}"
        )
        return False

    def _leave_node(self, deadline, cancel_requested_fn, search_left=None):
        """Leave the current node while preserving the planned search direction.

        Parameters:
        deadline: Absolute deadline of the whole edge operation.
        cancel_requested_fn: Optional callback returning True when motion must stop.
        search_left: Turn direction for all-white recovery; None keeps left search.
        """
        # Step 2: Protected leave. Node readings cannot mean "next node" here.
        self._log("leave_node start")
        started_at = self._time()
        clear_count = 0
        last_summary = None
        while self._time() < deadline and self._time() - started_at <= self.line_acquire_timeout:
            if self._cancel_requested(cancel_requested_fn):
                return False
            reading = self.line_follower.sensor.read()
            result = self.line_follower.apply_reading(
                reading,
                search_left=search_left is not False,
            )
            summary = _reading_summary(result)
            if summary != last_summary:
                self._log(
                    f"leave_node {summary} clear={clear_count}/{self.node_clear_samples}"
                )
                last_summary = summary

            if result.is_node:
                clear_count = 0
                self.motor.forward(
                    self.line_follower.forward_speed,
                    self.line_follower.forward_speed,
                )
            elif result.line_seen:
                clear_count += 1
            else:
                clear_count = 0

            if (
                self._time() - started_at >= self.leave_node_min_seconds
                and clear_count >= self.node_clear_samples
            ):
                self._log(f"leave_node success clear={clear_count}")
                return True

            self._sleep(self.delay_seconds)

        self._log(
            f"leave_node failed last={last_summary} clear={clear_count}/"
            f"{self.node_clear_samples}"
        )
        return False

    def _travel_edge(
        self,
        deadline,
        final_heading=None,
        cancel_requested_fn=None,
    ):
        # Step 3: Normal edge travel. This is the only dynamic-blocking phase.
        self._log("edge_travel start")
        self.obstacle_gate.start_edge()
        node_count = 0
        lost_since = None
        last_summary = None
        peak_node_count = 0

        while self._time() < deadline:
            if self._cancel_requested(cancel_requested_fn):
                return EdgeExecutionResult(
                    EDGE_CANCELED,
                    final_heading=final_heading,
                )
            result = self.line_follower.step()

            if result.is_node:
                node_count += 1
                peak_node_count = max(peak_node_count, node_count)
                summary = _reading_summary(result)
                if (
                    summary != last_summary
                    or node_count == 1
                    or node_count >= self.node_confirm_samples
                ):
                    self._log(
                        f"edge_travel {summary} node_count={node_count}/"
                        f"{self.node_confirm_samples}"
                    )
                    last_summary = summary
                if node_count >= self.node_confirm_samples:
                    if not self._center_on_node(deadline, cancel_requested_fn):
                        status = (
                            EDGE_CANCELED
                            if self._cancel_requested(cancel_requested_fn)
                            else EDGE_TIMEOUT
                        )
                        return EdgeExecutionResult(
                            status,
                            final_heading=final_heading,
                        )
                    return EdgeExecutionResult(
                        EDGE_REACHED_NEXT_NODE,
                        final_heading=final_heading,
                    )
            else:
                node_count = 0
                summary = _reading_summary(result)
                if summary != last_summary:
                    self._log(
                        f"edge_travel {summary} node_count={node_count}/"
                        f"{self.node_confirm_samples}"
                    )
                    last_summary = summary

            if self.obstacle_gate.check_blocked():
                self.motor.brake()
                self._log("edge_travel blocked_by_obstacle")
                return EdgeExecutionResult(
                    EDGE_BLOCKED_ON_PLANNED_EDGE,
                    final_heading=final_heading,
                )

            lost_since = self._update_line_loss(result, lost_since)
            if lost_since is not None and self._time() - lost_since >= self.line_lost_timeout:
                self.motor.brake()
                self._log(
                    f"edge_travel line_lost last={last_summary} "
                    f"peak_node_count={peak_node_count}"
                )
                return EdgeExecutionResult(
                    EDGE_LINE_LOST,
                    final_heading=final_heading,
                )

            self._sleep(self.delay_seconds)

        self.motor.brake()
        self._log(
            f"edge_travel timeout last={last_summary} peak_node_count={peak_node_count}"
        )
        return EdgeExecutionResult(EDGE_TIMEOUT, final_heading=final_heading)

    def _reverse_to_node_without_obstacle(
        self,
        deadline,
        final_heading=None,
        cancel_requested_fn=None,
    ):
        # Step 4: Recovery travel by reversing. No obstacle can seal a new edge.
        self._log("reverse_recovery start")
        node_count = 0
        lost_since = None
        last_summary = None
        peak_node_count = 0
        last_tracking_action = None

        while self._time() < deadline:
            if self._cancel_requested(cancel_requested_fn):
                return EdgeExecutionResult(
                    EDGE_CANCELED,
                    final_heading=final_heading,
                )
            if self.reverse_radar is not None:
                self.reverse_radar.tick()

            reading = self.line_follower.sensor.read()
            result = self._apply_reverse_reading(reading, last_tracking_action)
            if result.line_seen and not result.is_node:
                last_tracking_action = result.action

            if result.is_node:
                node_count += 1
                peak_node_count = max(peak_node_count, node_count)
                summary = _reading_summary(result)
                if (
                    summary != last_summary
                    or node_count == 1
                    or node_count >= self.node_confirm_samples
                ):
                    self._log(
                        f"reverse_recovery {summary} node_count={node_count}/"
                        f"{self.node_confirm_samples}"
                    )
                    last_summary = summary
                if node_count >= self.node_confirm_samples:
                    if not self._center_on_node(deadline, cancel_requested_fn):
                        status = (
                            EDGE_CANCELED
                            if self._cancel_requested(cancel_requested_fn)
                            else EDGE_TIMEOUT
                        )
                        return EdgeExecutionResult(
                            status,
                            final_heading=final_heading,
                        )
                    return EdgeExecutionResult(
                        EDGE_RECOVERED_TO_START_NODE,
                        final_heading=final_heading,
                    )
            else:
                node_count = 0
                summary = _reading_summary(result)
                if not result.line_seen and last_tracking_action is not None:
                    summary += f" reverse_search={last_tracking_action}"
                if summary != last_summary:
                    self._log(
                        f"reverse_recovery {summary} node_count={node_count}/"
                        f"{self.node_confirm_samples}"
                    )
                    last_summary = summary

            lost_since = self._update_line_loss(result, lost_since)
            if lost_since is not None and self._time() - lost_since >= self.line_lost_timeout:
                self.motor.brake()
                self._log(
                    f"reverse_recovery line_lost last={last_summary} "
                    f"peak_node_count={peak_node_count}"
                )
                return EdgeExecutionResult(
                    EDGE_LINE_LOST,
                    final_heading=final_heading,
                )

            self._sleep(self.delay_seconds)

        self.motor.brake()
        self._log(
            f"reverse_recovery timeout last={last_summary} "
            f"peak_node_count={peak_node_count}"
        )
        return EdgeExecutionResult(EDGE_TIMEOUT, final_heading=final_heading)

    def _apply_reverse_reading(self, reading, last_tracking_action=None):
        """Drive one reverse line-follow step from an already-read sample.

        Parameters:
        reading: LineReading-like object from the front line sensor.
        last_tracking_action: Last forward/left/right action seen on a valid line.
            A temporary all-white reading repeats that direction at reverse_speed.
        """
        action = decide_line_action(reading)

        if action == ACTION_NODE:
            self.motor.brake()
        elif action == ACTION_FORWARD:
            self.motor.backward(self.reverse_speed, self.reverse_speed)
        elif action == ACTION_LEFT:
            self.motor.backward(self.reverse_turn_speed, 0)
        elif action == ACTION_RIGHT:
            self.motor.backward(0, self.reverse_turn_speed)
        elif last_tracking_action == ACTION_FORWARD:
            self.motor.backward(self.reverse_speed, self.reverse_speed)
        elif last_tracking_action == ACTION_LEFT:
            self.motor.backward(self.reverse_speed, 0)
        elif last_tracking_action == ACTION_RIGHT:
            self.motor.backward(0, self.reverse_speed)
        else:
            self.motor.brake()

        return LineStepResult(
            reading=reading,
            action=action,
            is_node=is_at_node(reading),
            line_seen=is_line_seen(reading),
            centered_line=is_centered_line(reading),
        )

    def _center_on_node(self, deadline, cancel_requested_fn):
        """Move briefly toward the node center, then always brake.

        Parameters:
        deadline: Absolute deadline of the whole edge or recovery operation.
        cancel_requested_fn: Optional callback returning True when motion must stop.
        """
        completed = True
        if self.node_center_seconds > 0:
            self.motor.forward(
                self.line_follower.forward_speed,
                self.line_follower.forward_speed,
            )
            completed = self._wait_while_active(
                self.node_center_seconds,
                deadline,
                cancel_requested_fn,
            )
        self.motor.brake()
        return completed

    def _cancel_requested(self, cancel_requested_fn):
        """Check one external cancellation callback and brake before returning.

        Parameters:
        cancel_requested_fn: Optional zero-argument callback returning a boolean.

        Steps:
        Treat a missing callback as active motion. If the callback raises or returns
        True, brake before propagating the exception or reporting cancellation.
        """
        if cancel_requested_fn is None:
            return False
        try:
            requested = bool(cancel_requested_fn())
        except Exception:
            self.motor.brake()
            raise
        if requested:
            self.motor.brake()
            self._log("motion canceled")
        return requested

    def _wait_while_active(self, seconds, deadline, cancel_requested_fn):
        """Sleep in short intervals so powered motion can react to cancellation.

        Parameters:
        seconds: Requested motion duration.
        deadline: Absolute phase deadline from the monotonic clock.
        cancel_requested_fn: Optional cancellation callback.

        Steps:
        Limit the wait by the phase deadline, poll cancellation every 20 ms, and
        return False on cancellation or timeout.
        """
        requested_finish_at = self._time() + seconds
        finish_at = min(requested_finish_at, deadline)
        while self._time() < finish_at:
            if self._cancel_requested(cancel_requested_fn):
                return False
            remaining = finish_at - self._time()
            self._sleep(min(_CANCEL_POLL_SECONDS, remaining))
        if self._cancel_requested(cancel_requested_fn):
            return False
        # Real sleep commonly wakes slightly after finish_at. Only a deadline that
        # truncated the requested motion is a timeout; scheduler overshoot is not.
        return requested_finish_at <= deadline

    def _update_line_loss(self, result, lost_since):
        if result.line_seen:
            return None
        if lost_since is None:
            return self._time()
        return lost_since


def _reading_summary(result):
    """Format one line-step result for compact field-test logs.

    Parameters:
    result: LineStepResult-like object with reading/action/is_node/line_seen.
    """
    reading = result.reading
    return (
        f"LO={int(bool(reading.left_outer))} "
        f"LI={int(bool(reading.left_inner))} "
        f"RI={int(bool(reading.right_inner))} "
        f"RO={int(bool(reading.right_outer))} "
        f"node={int(bool(result.is_node))} "
        f"line={int(bool(result.line_seen))} "
        f"action={result.action}"
    )
