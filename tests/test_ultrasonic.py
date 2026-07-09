import unittest

from src.hardware.ultrasonic import UltrasonicSensor


class FakeGPIO:
    BCM = "BCM"
    OUT = "OUT"
    IN = "IN"
    LOW = False
    HIGH = True

    def __init__(self):
        self.mode = None
        self.warnings = None
        self.setup_calls = []
        self.output_calls = []
        self.cleanup_calls = []

    def setmode(self, mode):
        self.mode = mode

    def setwarnings(self, warnings):
        self.warnings = warnings

    def setup(self, pin, mode, initial=None):
        self.setup_calls.append((pin, mode, initial))

    def output(self, pin, value):
        self.output_calls.append((pin, value))

    def input(self, pin):
        return self.LOW

    def cleanup(self, pins=None):
        self.cleanup_calls.append(pins)


class UltrasonicSensorTest(unittest.TestCase):
    def test_close_only_cleans_ultrasonic_pins(self):
        gpio = FakeGPIO()
        sensor = UltrasonicSensor(
            gpio=gpio,
            trig_pin=17,
            echo_pin=18,
            threshold_cm=20,
            samples=1,
            timeout_s=0.001,
        )

        sensor.close()

        self.assertEqual(gpio.cleanup_calls, [(17, 18)])


if __name__ == "__main__":
    unittest.main()
