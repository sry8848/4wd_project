import unittest

from src.tasks.toll_clearance import (
    CLEARANCE_CANCELED,
    CLEARANCE_CLEARED,
    CLEARANCE_ERROR,
    CLEARANCE_TIMEOUT,
    TollClearanceTask,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeSource:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.last = self.snapshots[-1] if self.snapshots else (0, -1, False)

    def get_cached_reading(self):
        if self.snapshots:
            value = self.snapshots.pop(0)
            if isinstance(value, Exception):
                raise value
            self.last = value
        return self.last


class TollClearanceTaskTest(unittest.TestCase):
    def build_task(self, snapshots, timeout=1.0):
        self.clock = FakeClock()
        self.source = FakeSource(snapshots)
        return TollClearanceTask(
            self.source,
            clear_threshold_cm=20.0,
            confirm_samples=3,
            timeout_seconds=timeout,
            poll_seconds=0.1,
            monotonic_fn=self.clock.monotonic,
            sleep_fn=self.clock.sleep,
        )

    def test_counts_only_three_distinct_fresh_clear_readings(self):
        task = self.build_task(
            [
                (4, 10.0, True),
                (5, 25.0, False),
                (5, 25.0, False),
                (6, 30.0, False),
                (7, 22.0, False),
            ]
        )

        result = task.wait()

        self.assertEqual(result.outcome, CLEARANCE_CLEARED)
        self.assertEqual(result.last_distance_cm, 22.0)

    def test_blocked_or_invalid_fresh_reading_resets_clear_streak(self):
        task = self.build_task(
            [
                (1, 10.0, True),
                (2, 25.0, False),
                (3, -1.0, False),
                (4, 26.0, False),
                (5, 10.0, True),
                (6, 30.0, False),
                (7, 31.0, False),
                (8, 32.0, False),
            ]
        )

        result = task.wait()

        self.assertEqual(result.outcome, CLEARANCE_CLEARED)
        self.assertEqual(result.last_distance_cm, 32.0)

    def test_timeout_does_not_accept_stale_clear_cache(self):
        task = self.build_task([(9, 40.0, False)], timeout=0.3)

        result = task.wait()

        self.assertEqual(result.outcome, CLEARANCE_TIMEOUT)

    def test_cancel_and_sensor_error_are_explicit(self):
        task = self.build_task([(1, 10.0, True)])
        canceled = task.wait(cancel_requested_fn=lambda: True)
        self.assertEqual(canceled.outcome, CLEARANCE_CANCELED)

        task = self.build_task([RuntimeError("cache failed")])
        failed = task.wait()
        self.assertEqual(failed.outcome, CLEARANCE_ERROR)
        self.assertEqual(failed.error, "cache failed")


if __name__ == "__main__":
    unittest.main()
