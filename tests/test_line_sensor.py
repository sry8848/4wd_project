import unittest

from src import config
from src.hardware.line_sensor import LineReading, LineSensor


class FakeGPIO:
    BCM = "BCM"
    IN = "IN"
    HIGH = True
    LOW = False

    def __init__(self, values):
        self.values = values
        self.setup_calls = []
        self.cleanup_calls = []
        self.mode = None
        self.warnings = None

    def setmode(self, mode):
        self.mode = mode

    def setwarnings(self, warnings):
        self.warnings = warnings

    def setup(self, pin, mode):
        self.setup_calls.append((pin, mode))

    def input(self, pin):
        return self.values[pin]

    def cleanup(self, pins):
        self.cleanup_calls.append(tuple(pins))


class LineReadingTest(unittest.TestCase):
    def test_from_gpio_values_normalizes_low_level_to_black_line(self):
        reading = LineReading.from_gpio_values(False, True, False, True)

        self.assertTrue(reading.left_outer)
        self.assertFalse(reading.left_inner)
        self.assertTrue(reading.right_inner)
        self.assertFalse(reading.right_outer)


class LineSensorTest(unittest.TestCase):
    def test_read_returns_four_normalized_sensor_values_in_left_to_right_order(self):
        gpio = FakeGPIO(
            {
                config.LINE_SENSOR_LEFT_OUTER_PIN: False,
                config.LINE_SENSOR_LEFT_INNER_PIN: False,
                config.LINE_SENSOR_RIGHT_INNER_PIN: True,
                config.LINE_SENSOR_RIGHT_OUTER_PIN: True,
            }
        )
        sensor = LineSensor(gpio=gpio)

        reading = sensor.read()

        self.assertEqual(
            reading,
            LineReading(
                left_outer=True,
                left_inner=True,
                right_inner=False,
                right_outer=False,
            ),
        )
        self.assertEqual(
            gpio.setup_calls,
            [
                (config.LINE_SENSOR_LEFT_OUTER_PIN, gpio.IN),
                (config.LINE_SENSOR_LEFT_INNER_PIN, gpio.IN),
                (config.LINE_SENSOR_RIGHT_INNER_PIN, gpio.IN),
                (config.LINE_SENSOR_RIGHT_OUTER_PIN, gpio.IN),
            ],
        )

    def test_close_only_cleans_line_sensor_pins(self):
        gpio = FakeGPIO(
            {
                config.LINE_SENSOR_LEFT_OUTER_PIN: True,
                config.LINE_SENSOR_LEFT_INNER_PIN: True,
                config.LINE_SENSOR_RIGHT_INNER_PIN: True,
                config.LINE_SENSOR_RIGHT_OUTER_PIN: True,
            }
        )
        sensor = LineSensor(gpio=gpio)

        sensor.close()

        self.assertEqual(
            gpio.cleanup_calls,
            [
                (
                    config.LINE_SENSOR_LEFT_OUTER_PIN,
                    config.LINE_SENSOR_LEFT_INNER_PIN,
                    config.LINE_SENSOR_RIGHT_INNER_PIN,
                    config.LINE_SENSOR_RIGHT_OUTER_PIN,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
