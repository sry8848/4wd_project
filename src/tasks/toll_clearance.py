"""Wait for fresh cached ultrasonic readings to confirm a cleared toll gate."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Optional


CLEARANCE_CLEARED = "cleared"
CLEARANCE_TIMEOUT = "timeout"
CLEARANCE_CANCELED = "canceled"
CLEARANCE_ERROR = "error"


@dataclass(frozen=True)
class TollClearanceResult:
    """Final result of one stopped toll-clearance wait.

    Parameters:
    outcome: cleared, timeout, canceled, or error.
    last_distance_cm: Last fresh distance observed, including invalid negative values.
    error: Sensor read error text when outcome is error.
    """

    outcome: str
    last_distance_cm: Optional[float]
    error: Optional[str] = None


class TollClearanceTask:
    """Confirm consecutive fresh clear readings without measuring synchronously.

    Parameters:
    source: UltrasonicSensor-compatible object providing get_cached_reading().
    clear_threshold_cm: Valid distances at or above this value are clear.
    confirm_samples: Consecutive fresh clear readings required.
    timeout_seconds: Maximum wait after taking the initial sequence snapshot.
    poll_seconds: Delay between cache polls; it does not trigger GPIO measurement.
    monotonic_fn/sleep_fn: Runtime clock functions.
    """

    def __init__(
        self,
        source,
        *,
        clear_threshold_cm: float = 20.0,
        confirm_samples: int = 3,
        timeout_seconds: float = 60.0,
        poll_seconds: float = 0.02,
        monotonic_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        if clear_threshold_cm <= 0:
            raise ValueError("clear_threshold_cm must be greater than 0")
        if confirm_samples <= 0:
            raise ValueError("confirm_samples must be greater than 0")
        if timeout_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("clearance timing values must be greater than 0")
        self.source = source
        self.clear_threshold_cm = float(clear_threshold_cm)
        self.confirm_samples = confirm_samples
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self._monotonic = monotonic_fn
        self._sleep = sleep_fn

    def wait(
        self,
        cancel_requested_fn: Optional[Callable[[], bool]] = None,
    ) -> TollClearanceResult:
        """Wait for distinct valid clear samples, resetting on blocked or invalid data.

        Steps:
        Snapshot the current sequence so pre-wait cache is ignored. Count only newer
        valid distances at or above the threshold; any blocked or invalid fresh sample
        resets the streak. Cancellation, timeout, and read errors return explicitly.
        """

        try:
            last_sequence, last_distance, _obstructed = self.source.get_cached_reading()
        except Exception as exc:
            return TollClearanceResult(CLEARANCE_ERROR, None, str(exc))

        deadline = self._monotonic() + self.timeout_seconds
        clear_count = 0
        while self._monotonic() < deadline:
            if cancel_requested_fn is not None and cancel_requested_fn():
                return TollClearanceResult(CLEARANCE_CANCELED, last_distance)
            try:
                sequence, distance, obstructed = self.source.get_cached_reading()
            except Exception as exc:
                return TollClearanceResult(CLEARANCE_ERROR, last_distance, str(exc))
            if sequence <= last_sequence:
                self._sleep(self.poll_seconds)
                continue

            last_sequence = sequence
            last_distance = distance
            valid_clear = (
                distance is not None
                and float(distance) >= self.clear_threshold_cm
                and not bool(obstructed)
            )
            if valid_clear:
                clear_count += 1
                if clear_count >= self.confirm_samples:
                    return TollClearanceResult(CLEARANCE_CLEARED, float(distance))
            else:
                clear_count = 0
            self._sleep(self.poll_seconds)

        if cancel_requested_fn is not None and cancel_requested_fn():
            return TollClearanceResult(CLEARANCE_CANCELED, last_distance)
        return TollClearanceResult(CLEARANCE_TIMEOUT, last_distance)
