import unittest

from src.tasks.reverse_radar import CachedReverseRadar


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class FakeSource:
    def __init__(self, distance):
        self.last_distance = distance

    def read_filtered(self):
        raise AssertionError("CachedReverseRadar must not measure distance")


class FakeBuzzer:
    def __init__(self):
        self.calls = []

    def on(self):
        self.calls.append("on")

    def off(self):
        self.calls.append("off")


class CachedReverseRadarTest(unittest.TestCase):
    def test_tick_uses_cached_distance_without_blocking_measurement(self):
        clock = FakeClock()
        source = FakeSource(40)
        buzzer = FakeBuzzer()
        radar = CachedReverseRadar(source, buzzer, time_fn=clock.monotonic)

        radar.tick()
        clock.now = 0.11
        radar.tick()
        clock.now = 0.60
        radar.tick()

        self.assertEqual(buzzer.calls, ["on", "off", "on"])

    def test_stop_silences_continuous_close_warning(self):
        clock = FakeClock()
        source = FakeSource(10)
        buzzer = FakeBuzzer()
        radar = CachedReverseRadar(source, buzzer, time_fn=clock.monotonic)

        radar.tick()
        radar.stop()

        self.assertEqual(buzzer.calls, ["on", "off"])


if __name__ == "__main__":
    unittest.main()
