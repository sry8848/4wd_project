"""RGB LED module for the Yahboom 4WD car.

Controls a common-anode (or common-cathode) RGB LED through three PWM
channels, allowing full-colour mixing and blink patterns.

This layer only answers *how* to light the LED — it does not decide
*when* or *what colour*.  Upper-layer tasks combine this with sensor
or motor state to choose colours.

Pinout (BCM):  R=22, G=27, B=24  (from Yahboom official examples).

Usage::

    from src.hardware.led import RgbLed

    led = RgbLed()
    led.set_color(100, 0, 0)    # red, full brightness
    led.set_color(0, 100, 0)    # green
    led.set_color(50, 50, 0)    # yellow (dim)
    led.red()                   # shortcut
    led.blink(3, 0.2, 0.2)      # flash red 3 times
    led.close()
"""

from src import config
import time


class RgbLed:
    """Control an RGB LED through three PWM GPIO channels.

    Parameters
    ----------
    gpio : module or None
        Pass a mock GPIO for testing on non-RPi machines.  ``None``
        imports ``RPi.GPIO`` at runtime.
    """

    # Named-colour lookup: (R_duty, G_duty, B_duty) in 0-100 range.
    COLORS = {
        "red":     (100, 0, 0),
        "green":   (0, 100, 0),
        "blue":    (0, 0, 100),
        "yellow":  (100, 100, 0),
        "purple":  (100, 0, 100),
        "cyan":    (0, 100, 100),
        "white":   (100, 100, 100),
        "off":     (0, 0, 0),
    }

    def __init__(self, gpio=None):
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "RPi.GPIO is not available; pass gpio=MockGPIO() for tests"
                ) from exc
        self._gpio = gpio

        self._pin_r = config.LED_R_PIN
        self._pin_g = config.LED_G_PIN
        self._pin_b = config.LED_B_PIN
        self._freq = config.LED_PWM_FREQUENCY

        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setwarnings(False)

        for pin in (self._pin_r, self._pin_g, self._pin_b):
            self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.LOW)

        self._pwm_r = self._gpio.PWM(self._pin_r, self._freq)
        self._pwm_g = self._gpio.PWM(self._pin_g, self._freq)
        self._pwm_b = self._gpio.PWM(self._pin_b, self._freq)

        self._pwm_r.start(0)
        self._pwm_g.start(0)
        self._pwm_b.start(0)

        # Store current colour for read-back.
        self._r = 0
        self._g = 0
        self._b = 0

    # ------------------------------------------------------------------
    #  Colour control
    # ------------------------------------------------------------------

    def set_color(self, r, g, b):
        """Set the LED to an arbitrary RGB colour.

        Parameters
        ----------
        r, g, b : int
            Brightness 0–100 for each channel.  (0 = off, 100 = max.)
        """
        self._r = self._clamp(r)
        self._g = self._clamp(g)
        self._b = self._clamp(b)
        self._pwm_r.ChangeDutyCycle(self._r)
        self._pwm_g.ChangeDutyCycle(self._g)
        self._pwm_b.ChangeDutyCycle(self._b)

    def set_color_name(self, name):
        """Set the LED to a named colour.

        Supported names: ``red``, ``green``, ``blue``, ``yellow``,
        ``purple``, ``cyan``, ``white``, ``off``.
        """
        rgb = self.COLORS.get(name)
        if rgb is None:
            raise ValueError(f"unknown colour '{name}'; "
                             f"choose from {list(self.COLORS)}")
        self.set_color(*rgb)

    @staticmethod
    def _clamp(v):
        return max(0, min(100, int(v)))

    # ------------------------------------------------------------------
    #  Named-colour convenience methods
    # ------------------------------------------------------------------

    def red(self):
        self.set_color_name("red")

    def green(self):
        self.set_color_name("green")

    def blue(self):
        self.set_color_name("blue")

    def yellow(self):
        self.set_color_name("yellow")

    def purple(self):
        self.set_color_name("purple")

    def cyan(self):
        self.set_color_name("cyan")

    def white(self):
        self.set_color_name("white")

    def off(self):
        self.set_color_name("off")

    # ------------------------------------------------------------------
    #  Blink
    # ------------------------------------------------------------------

    def blink(self, times=3, on_time=0.2, off_time=0.2,
              on_color="red", off_color="off"):
        """Blink the LED repeatedly.

        Parameters
        ----------
        times : int
            Number of blinks.
        on_time : float
            Seconds the LED stays *on* per blink.
        off_time : float
            Seconds the LED stays *off* between blinks.
        on_color : str or tuple
            Colour name or ``(r, g, b)`` tuple during the on phase.
        off_color : str or tuple
            Colour during the off phase (usually ``"off"``).
        """
        for i in range(times):
            self._apply_color(on_color)
            time.sleep(on_time)
            self._apply_color(off_color)
            if i < times - 1:
                time.sleep(off_time)

    def _apply_color(self, color):
        if isinstance(color, str):
            self.set_color_name(color)
        else:
            self.set_color(*color)

    # ------------------------------------------------------------------
    #  Status-signal convenience (matching buzzer signals)
    # ------------------------------------------------------------------

    def signal_startup(self):
        """Brief green flash → ready."""
        self.blink(1, 0.3, 0, "green")

    def signal_obstacle(self):
        """Flash red twice → obstacle."""
        self.blink(2, 0.15, 0.15, "red")

    def signal_arrival(self):
        """Flash green twice → reached target."""
        self.blink(2, 0.25, 0.15, "green")

    def signal_photo(self):
        """Quick white flash → photo taken."""
        self.blink(3, 0.08, 0.06, "white")

    def signal_complete(self):
        """Rapid green blinks → mission done."""
        self.blink(5, 0.06, 0.06, "green")

    def signal_error(self):
        """Solid red for 1 s → error."""
        self.red()
        time.sleep(1.0)
        self.off()

    # ------------------------------------------------------------------
    #  Resource release
    # ------------------------------------------------------------------

    def close(self):
        """Turn the LED off and release PWM / GPIO resources."""
        self.off()
        self._pwm_r.stop()
        self._pwm_g.stop()
        self._pwm_b.stop()
        self._gpio.cleanup()
