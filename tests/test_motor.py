import unittest

from src import config
from src.hardware.motor import MotorController


class FakePwm:
    def __init__(self):
        self.duty_cycles = []
        self.stopped = False

    def start(self, duty_cycle):
        self.duty_cycles.append(("start", duty_cycle))

    def ChangeDutyCycle(self, duty_cycle):
        self.duty_cycles.append(("change", duty_cycle))

    def stop(self):
        self.stopped = True


class FakeGPIO:
    BCM = "BCM"
    OUT = "OUT"
    HIGH = True
    LOW = False

    def __init__(self):
        self.mode = None
        self.warnings = None
        self.setup_calls = []
        self.output_calls = []
        self.cleanup_calls = []
        self.pwms = []

    def setmode(self, mode):
        self.mode = mode

    def setwarnings(self, warnings):
        self.warnings = warnings

    def setup(self, pin, mode, initial=None):
        self.setup_calls.append((pin, mode, initial))

    def output(self, pin, value):
        self.output_calls.append((pin, value))

    def PWM(self, pin, frequency):
        pwm = FakePwm()
        self.pwms.append((pin, frequency, pwm))
        return pwm

    def cleanup(self, pins=None):
        self.cleanup_calls.append(pins)


class MotorControllerTest(unittest.TestCase):
    def test_close_brakes_stops_pwm_and_only_cleans_motor_pins(self):
        gpio = FakeGPIO()
        motor = MotorController(gpio=gpio)

        motor.close()

        self.assertEqual(
            gpio.cleanup_calls,
            [
                (
                    config.MOTOR_ENA,
                    config.MOTOR_IN1,
                    config.MOTOR_IN2,
                    config.MOTOR_ENB,
                    config.MOTOR_IN3,
                    config.MOTOR_IN4,
                )
            ],
        )
        self.assertTrue(gpio.pwms[0][2].stopped)
        self.assertTrue(gpio.pwms[1][2].stopped)
        self.assertIn((config.MOTOR_IN1, gpio.LOW), gpio.output_calls)
        self.assertIn((config.MOTOR_IN4, gpio.LOW), gpio.output_calls)


if __name__ == "__main__":
    unittest.main()
