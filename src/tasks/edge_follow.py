"""Execute one planned grid edge with protected line following.

The edge executor does not know the map and does not run A*. It only tries to
leave the current trusted node, travel along the planned edge, report a blocked
edge when the ultrasonic gate confirms one, or recover back to the start node.
"""

from dataclasses import dataclass
import time
from typing import Optional

from src.tasks.line_follow import ACTION_SEARCH_LEFT


EDGE_REACHED_NEXT_NODE = "reached_next_node"
EDGE_BLOCKED_ON_PLANNED_EDGE = "blocked_on_planned_edge"
EDGE_RECOVERED_TO_START_NODE = "recovered_to_start_node"
EDGE_TURN_FAILED = "turn_failed"
EDGE_LEAVE_NODE_FAILED = "leave_node_failed"
EDGE_LINE_LOST = "line_lost"
EDGE_TIMEOUT = "timeout"
EDGE_RECOVERY_FAILED = "recovery_failed"

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
    """Expose a background ultrasonic cache as an is_obstructed() sensor.

    Parameters:
    source: Object with an obstacle_detected boolean updated by monitoring.
    """

    def __init__(self, source):
        self.source = source

    def is_obstructed(self):
        """Return the latest cached obstacle state without measuring now."""
        return bool(self.source.obstacle_detected)


class ObstacleGate:
    """Debounce and arm ultrasonic readings for the current planned edge.

    Parameters:
    sensor: Optional object providing is_obstructed().
    arm_delay: Seconds to wait after edge travel starts before reading.
    clear_samples: Safe readings required before obstacle hits are trusted.
    confirm_samples: Consecutive obstacle readings required to block the edge.
    time_fn: Monotonic time function, injectable for tests.
    """

    def __init__(
        self,
        sensor=None,
        arm_delay=0.3,
        clear_samples=1,
        confirm_samples=2,
        time_fn=None,
    ):
        if arm_delay < 0:
            raise ValueError("arm_delay must be >= 0")
        if clear_samples < 0:
            raise ValueError("clear_samples must be >= 0")
        if confirm_samples <= 0:
            raise ValueError("confirm_samples must be > 0")

        self.sensor = sensor
        self.arm_delay = arm_delay
        self.clear_samples = clear_samples
        self.confirm_samples = confirm_samples
        self._time = time_fn if time_fn is not None else time.monotonic
        self.started_at = None
        self.safe_count = 0
        self.hit_count = 0

    def start_edge(self):
        """Reset the gate for a new EDGE_TRAVEL phase."""
        self.started_at = self._time()
        self.safe_count = 0
        self.hit_count = 0

    def check_blocked(self):
        """Return True only when this edge has a confirmed obstacle.

        This method is intentionally called only by EDGE_TRAVEL. Turning,
        leaving a node, searching for a line, and recovery never read the
        ultrasonic cache through this gate.
        """
        if self.sensor is None or self.started_at is None:
            return False

        if self._time() - self.started_at < self.arm_delay:
            return False

        if not self.sensor.is_obstructed():
            self.safe_count += 1
            self.hit_count = 0
            return False

        if self.safe_count < self.clear_samples:
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
    turn_rough_seconds: Coarse 90-degree turn duration.
    uturn_rough_seconds: Coarse 180-degree turn duration.
    uturn_seconds: Deprecated alias for uturn_rough_seconds.
    leave_node_min_seconds: Minimum protected time before leaving can succeed.
    node_clear_samples: Consecutive non-node line samples required to leave.
    node_confirm_samples: Consecutive node samples required to enter a node.
    node_center_seconds: Short forward push after confirming a node.
    obstacle_arm_delay: Delay before obstacle readings can block an edge.
    obstacle_clear_samples: Safe readings required before obstacle confirmation.
    obstacle_confirm_samples: Obstacle readings required before blocking an edge.
    line_acquire_timeout: Maximum protected leave/search time.
    line_lost_timeout: Maximum all-white line loss time during travel.
    delay_seconds: Loop delay between sensor samples.
    time_fn/sleep_fn: Injectable time functions for deterministic tests.
    """

    def __init__(
        self,
        line_follower,
        obstacle_sensor=None,
        turn_speed=30,
        turn_rough_seconds=0.5,
        uturn_rough_seconds=1.2,
        uturn_seconds=None,
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
        time_fn=None,
        sleep_fn=None,
    ):
        if uturn_seconds is not None:
            uturn_rough_seconds = uturn_seconds
        if turn_rough_seconds < 0 or uturn_rough_seconds < 0:
            raise ValueError("rough turn seconds must be >= 0")
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
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be >= 0")

        self.line_follower = line_follower
        self.motor = line_follower.motor
        self.obstacle_sensor = obstacle_sensor
        self.turn_speed = turn_speed
        self.turn_rough_seconds = turn_rough_seconds
        self.uturn_rough_seconds = uturn_rough_seconds
        self.leave_node_min_seconds = leave_node_min_seconds
        self.node_clear_samples = node_clear_samples
        self.node_confirm_samples = node_confirm_samples
        self.node_center_seconds = node_center_seconds
        self.line_acquire_timeout = line_acquire_timeout
        self.line_lost_timeout = line_lost_timeout
        self.delay_seconds = delay_seconds
        self._time = time_fn if time_fn is not None else time.monotonic
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self.obstacle_gate = ObstacleGate(
            sensor=obstacle_sensor,
            arm_delay=obstacle_arm_delay,
            clear_samples=obstacle_clear_samples,
            confirm_samples=obstacle_confirm_samples,
            time_fn=self._time,
        )

    def execute_planned_edge(self, current_heading, target_heading, max_seconds):
        """Align to target_heading, leave the node, then travel the edge.

        Parameters:
        current_heading: Current trusted heading, or None to skip coarse align.
        target_heading: Heading of the planned edge, or None to keep heading.
        max_seconds: Whole-edge timeout including turn, leave, and travel.
        """
        if max_seconds <= 0:
            raise ValueError("max_seconds must be > 0")

        deadline = self._time() + max_seconds
        if not self._align_to_heading(current_heading, target_heading, deadline):
            self.motor.brake()
            return EdgeExecutionResult(EDGE_TURN_FAILED, reason=EDGE_TIMEOUT)

        if not self._leave_node(deadline):
            self.motor.brake()
            return EdgeExecutionResult(EDGE_LEAVE_NODE_FAILED, reason=EDGE_TIMEOUT)

        return self._travel_edge(deadline, final_heading=target_heading)

    def follow_edge(self, max_seconds):
        """Legacy wrapper that executes the current heading without alignment.

        Parameters:
        max_seconds: Whole-edge timeout. New callers should use
            execute_planned_edge().
        """
        return self.execute_planned_edge(None, None, max_seconds).status

    def recover_to_start_node(self, return_heading=None, max_seconds=None):
        """Turn around once and follow the line back to the start node.

        Parameters:
        return_heading: Heading after recovery, normally opposite(target_heading).
            For backward compatibility, a numeric first argument is treated as
            max_seconds.
        max_seconds: Recovery timeout.
        """
        if max_seconds is None and isinstance(return_heading, (int, float)):
            max_seconds = return_heading
            return_heading = None
        if max_seconds is None or max_seconds <= 0:
            raise ValueError("max_seconds must be > 0")

        deadline = self._time() + max_seconds
        if not self._rough_turn(left=True, seconds=self.uturn_rough_seconds, deadline=deadline):
            self.motor.brake()
            return EdgeExecutionResult(
                EDGE_RECOVERY_FAILED,
                final_heading=return_heading,
                reason=EDGE_TIMEOUT,
            )

        result = self._travel_to_node_without_obstacle(deadline, final_heading=return_heading)
        if result.status == EDGE_RECOVERED_TO_START_NODE:
            return result

        self.motor.brake()
        return EdgeExecutionResult(
            EDGE_RECOVERY_FAILED,
            final_heading=return_heading,
            reason=result.status,
        )

    def _align_to_heading(self, current_heading, target_heading, deadline):
        # Step 1: Coarse turn only. No ultrasonic, no node recognition here.
        if current_heading is None or target_heading is None:
            return self._time() < deadline
        if current_heading not in _HEADINGS or target_heading not in _HEADINGS:
            raise ValueError("heading must be north/east/south/west")

        current_index = _HEADINGS.index(current_heading)
        target_index = _HEADINGS.index(target_heading)
        diff = (target_index - current_index) % len(_HEADINGS)

        if diff == 0:
            return self._time() < deadline
        if diff == 1:
            return self._rough_turn(left=False, seconds=self.turn_rough_seconds, deadline=deadline)
        if diff == 2:
            return self._rough_turn(left=True, seconds=self.uturn_rough_seconds, deadline=deadline)
        return self._rough_turn(left=True, seconds=self.turn_rough_seconds, deadline=deadline)

    def _rough_turn(self, left, seconds, deadline):
        if self._time() >= deadline:
            return False
        if seconds > 0:
            if left:
                self.motor.spin_left(self.turn_speed, self.turn_speed)
            else:
                self.motor.spin_right(self.turn_speed, self.turn_speed)
            self._sleep(seconds)
        self.motor.brake()
        return self._time() < deadline

    def _leave_node(self, deadline):
        # Step 2: Protected leave. Node readings cannot mean "next node" here.
        started_at = self._time()
        clear_count = 0
        while self._time() < deadline and self._time() - started_at <= self.line_acquire_timeout:
            reading = self.line_follower.sensor.read()
            result = self.line_follower.apply_reading(reading)

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
                return True

            self._sleep(self.delay_seconds)

        return False

    def _travel_edge(self, deadline, final_heading=None):
        # Step 3: Normal edge travel. This is the only dynamic-blocking phase.
        self.obstacle_gate.start_edge()
        node_count = 0
        lost_since = None

        while self._time() < deadline:
            result = self.line_follower.step()

            if result.is_node:
                node_count += 1
                if node_count >= self.node_confirm_samples:
                    self._center_on_node()
                    return EdgeExecutionResult(
                        EDGE_REACHED_NEXT_NODE,
                        final_heading=final_heading,
                    )
            else:
                node_count = 0

            if self._stable_tracking(result) and self.obstacle_gate.check_blocked():
                self.motor.brake()
                return EdgeExecutionResult(
                    EDGE_BLOCKED_ON_PLANNED_EDGE,
                    final_heading=final_heading,
                )

            lost_since = self._update_line_loss(result, lost_since)
            if lost_since is not None and self._time() - lost_since >= self.line_lost_timeout:
                self.motor.brake()
                return EdgeExecutionResult(
                    EDGE_LINE_LOST,
                    final_heading=final_heading,
                )

            self._sleep(self.delay_seconds)

        self.motor.brake()
        return EdgeExecutionResult(EDGE_TIMEOUT, final_heading=final_heading)

    def _travel_to_node_without_obstacle(self, deadline, final_heading=None):
        # Step 4: Recovery travel. Ultrasonic is ignored and no edge can be sealed.
        node_count = 0
        lost_since = None

        while self._time() < deadline:
            result = self.line_follower.step()

            if result.is_node:
                node_count += 1
                if node_count >= self.node_confirm_samples:
                    self._center_on_node()
                    return EdgeExecutionResult(
                        EDGE_RECOVERED_TO_START_NODE,
                        final_heading=final_heading,
                    )
            else:
                node_count = 0

            lost_since = self._update_line_loss(result, lost_since)
            if lost_since is not None and self._time() - lost_since >= self.line_lost_timeout:
                self.motor.brake()
                return EdgeExecutionResult(
                    EDGE_LINE_LOST,
                    final_heading=final_heading,
                )

            self._sleep(self.delay_seconds)

        self.motor.brake()
        return EdgeExecutionResult(EDGE_TIMEOUT, final_heading=final_heading)

    def _center_on_node(self):
        if self.node_center_seconds > 0:
            self.motor.forward(
                self.line_follower.forward_speed,
                self.line_follower.forward_speed,
            )
            self._sleep(self.node_center_seconds)
        self.motor.brake()

    def _stable_tracking(self, result):
        return (
            result.line_seen
            and not result.is_node
            and result.action != ACTION_SEARCH_LEFT
        )

    def _update_line_loss(self, result, lost_since):
        if result.line_seen:
            return None
        if lost_since is None:
            return self._time()
        return lost_since
