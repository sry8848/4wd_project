"""Driving-lights task: LED colour follows the car's motion state.

Combines ``MotorController`` and ``RgbLed`` so the LED automatically
shows the current driving state::

    Forward  → 🟢 green
    Backward → 🔴 red
    Turning  → 🟡 yellow (left / right / spin)
    Stopped  → ⚫ off

Usage::

    from src.tasks.driving_lights import DrivingLights

    dl = DrivingLights()
    dl.forward(50, 50)       # car moves forward, LED turns green
    dl.backward(40, 40)      # car reverses, LED turns red
    dl.spin_left(50, 50)     # spin, LED turns yellow
    dl.brake()               # stop, LED turns off
    dl.close()
"""

import time


class DrivingLights:
    """Motor driver wrapper that sets the LED colour per action.

    Parameters
    ----------
    motor : MotorController or None
        Created automatically if ``None``.
    led : RgbLed or None
        Created automatically if ``None``.
    """

    def __init__(self, motor=None, led=None):
        if motor is None:
            from src.hardware.motor import MotorController
            motor = MotorController()
        if led is None:
            from src.hardware.led import RgbLed
            led = RgbLed()

        self.motor = motor
        self.led = led

    # ------------------------------------------------------------------
    #  Forward
    # ------------------------------------------------------------------

    def forward(self, left_speed, right_speed):
        """Drive forward with green LED."""
        self.led.green()
        self.motor.forward(left_speed, right_speed)

    # ------------------------------------------------------------------
    #  Backward
    # ------------------------------------------------------------------

    def backward(self, left_speed, right_speed):
        """Reverse with red LED."""
        self.led.red()
        self.motor.backward(left_speed, right_speed)

    # ------------------------------------------------------------------
    #  Turns (non-zero radius)
    # ------------------------------------------------------------------

    def left(self, left_speed, right_speed):
        """Turn left with yellow LED."""
        self.led.yellow()
        self.motor.left(left_speed, right_speed)

    def right(self, left_speed, right_speed):
        """Turn right with yellow LED."""
        self.led.yellow()
        self.motor.right(left_speed, right_speed)

    # ------------------------------------------------------------------
    #  Spins (zero-radius turns)
    # ------------------------------------------------------------------

    def spin_left(self, left_speed, right_speed):
        """Spin left with yellow LED."""
        self.led.yellow()
        self.motor.spin_left(left_speed, right_speed)

    def spin_right(self, left_speed, right_speed):
        """Spin right with yellow LED."""
        self.led.yellow()
        self.motor.spin_right(left_speed, right_speed)

    # ------------------------------------------------------------------
    #  Stop
    # ------------------------------------------------------------------

    def brake(self):
        """Stop and turn the LED off."""
        self.motor.brake()
        self.led.off()

    # ------------------------------------------------------------------
    #  Resource release
    # ------------------------------------------------------------------

    def close(self):
        """Stop car, turn off LED, release hardware."""
        try:
            self.brake()
        finally:
            try:
                self.motor.close()
            finally:
                self.led.close()
