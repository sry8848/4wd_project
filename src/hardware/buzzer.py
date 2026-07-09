"""Active buzzer for audible alerts on the Yahboom 4WD car.

Provides a ``Buzzer`` class with basic beep control and status signals.

This layer only answers *how* to make a sound — it does not decide
*when* or *why*.  Upper-layer tasks (e.g. ``tasks.reverse_radar``)
combine ``Buzzer`` with sensors to implement scenario logic.

The buzzer shares BCM pin 8 with the on-board key button (common on
Yahboom cars).  Setting the pin HIGH drives the buzzer; the button
pulls it LOW.  This is safe as long as you do not read the pin as an
input at the same time.

Usage::

    from src.hardware.buzzer import Buzzer

    buzzer = Buzzer()
    buzzer.beep(0.2)                 # single 200 ms beep
    buzzer.beep_pattern(3)           # three quick beeps
    buzzer.signal_startup()          # "ready" notification
    buzzer.close()
"""

from src import config
import time


class Buzzer:
    """Drive an active buzzer through one GPIO pin.

    Parameters
    ----------
    pin : int or None
        BCM pin number.  Falls back to ``config.BUZZER_PIN`` (8).
    gpio : module or None
        Pass a mock GPIO for testing on non-RPi machines.  ``None``
        imports ``RPi.GPIO`` at runtime.
    """

    def __init__(self, pin=None, gpio=None):
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "RPi.GPIO is not available; pass gpio=MockGPIO() for tests"
                ) from exc
        self._gpio = gpio
        self._pin = pin if pin is not None else config.BUZZER_PIN

        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setwarnings(False)
        self._gpio.setup(self._pin, self._gpio.OUT, initial=self._gpio.LOW)

    # ------------------------------------------------------------------
    #  Low-level helpers
    # ------------------------------------------------------------------

    def on(self):
        """Turn the buzzer on (set pin HIGH)."""
        self._gpio.output(self._pin, self._gpio.HIGH)

    def off(self):
        """Turn the buzzer off (set pin LOW)."""
        self._gpio.output(self._pin, self._gpio.LOW)

    # ------------------------------------------------------------------
    #  Basic beep patterns
    # ------------------------------------------------------------------

    def beep(self, duration=0.2):
        """Single beep for *duration* seconds."""
        self.on()
        time.sleep(duration)
        self.off()

    def beep_pattern(self, times=2, on_time=0.15, off_time=0.15):
        """Repeated short beeps.

        Examples::

            buzzer.beep_pattern(1)          # single blip
            buzzer.beep_pattern(2)          # "beep-beep"
            buzzer.beep_pattern(3, 0.1)     # three rapid beeps
        """
        for i in range(times):
            self.on()
            time.sleep(on_time)
            self.off()
            if i < times - 1:
                time.sleep(off_time)

    # ------------------------------------------------------------------
    #  Status signals
    # ------------------------------------------------------------------

    def signal_startup(self):
        """One medium beep → ready."""
        self.beep_pattern(1, 0.3)

    def signal_obstacle(self):
        """Two quick beeps → obstacle ahead."""
        self.beep_pattern(2, 0.12, 0.10)

    def signal_arrival(self):
        """Two longer beeps → reached target."""
        self.beep_pattern(2, 0.25, 0.15)

    def signal_photo(self):
        """Three very quick beeps → photo taken."""
        self.beep_pattern(3, 0.08, 0.06)

    def signal_complete(self):
        """Five rapid beeps → mission done."""
        self.beep_pattern(5, 0.06, 0.06)

    def signal_error(self):
        """Long continuous beep → something went wrong."""
        self.beep(1.0)

    # ------------------------------------------------------------------
    #  Resource release
    # ------------------------------------------------------------------

    def close(self):
        """Turn off the buzzer and release only its GPIO pin."""
        try:
            self.off()
        finally:
            self._gpio.cleanup(self._pin)
