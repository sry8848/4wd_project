"""Active buzzer for audible alerts on the Yahboom 4WD car.

Provides a ``Buzzer`` class with:

- Simple beep and beep-pattern output.
- **Reverse-radar mode** — beep interval shortens as a distance value
  decreases, designed to pair with ``UltrasonicSensor``.

The buzzer shares BCM pin 8 with the on-board key button (common on
Yahboom cars).  Setting the pin HIGH drives the buzzer; the button
pulls it LOW.  This is safe as long as you do not read the pin as an
input at the same time.

Usage::

    from src.hardware.buzzer import Buzzer

    buzzer = Buzzer()
    buzzer.beep(0.2)                 # single 200 ms beep
    buzzer.radar_beep(35)            # one beep at "35 cm" urgency
    buzzer.signal_startup()          # "ready" notification
    buzzer.close()
"""

from src import config
import time
import threading


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

        # Background-radar thread state.
        self._looping = False
        self._loop_thread = None

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
    #  Reverse-radar mode
    # ------------------------------------------------------------------

    def radar_beep(self, distance_cm):
        """One beep whose urgency matches *distance_cm*.

        Call this from a loop::

            while True:
                d = sensor.read_filtered()
                buzzer.radar_beep(d)
                time.sleep(0.05)

        ``radar_beep`` blocks for a while (silent pause after each beep)
        so the calling loop paces itself naturally.

        Urgency levels::

            distance > 100   → silent (returns immediately)
            100 … 51         → slow  beep, long  pause  (every ~1.1 s)
            50 … 31          → medium beep, medium pause (every ~0.6 s)
            30 … 16          → quick beep, short pause  (every ~0.3 s)
            15 … 1           → continuous tone
            -1 (timeout)     → silent
        """
        if distance_cm < 0 or distance_cm > 100:
            return

        if distance_cm > 50:          # far — slow
            self.beep(0.1)
            time.sleep(1.0)
        elif distance_cm > 30:        # medium
            self.beep(0.1)
            time.sleep(0.5)
        elif distance_cm > 15:        # close — quick
            self.beep(0.08)
            time.sleep(0.2)
        else:                          # very close — continuous
            self.on()
            time.sleep(0.1)

    def start_radar(self, sensor, interval=0.05):
        """Run reverse-radar in a background daemon thread.

        Parameters
        ----------
        sensor : UltrasonicSensor
            Any object with a ``read_filtered()`` method returning cm.
        interval : float
            Seconds between distance readings.
        """
        if self._looping:
            return
        self._looping = True
        self._loop_thread = threading.Thread(
            target=self._radar_loop,
            args=(sensor, interval),
            daemon=True,
            name="buzzer-radar",
        )
        self._loop_thread.start()

    def stop_radar(self):
        """Stop the background radar thread and silence the buzzer."""
        self._looping = False
        if self._loop_thread:
            self._loop_thread.join(timeout=2)
            self._loop_thread = None
        self.off()

    def _radar_loop(self, sensor, interval):
        while self._looping:
            d = sensor.read_filtered()
            self.radar_beep(d)
            if 0 < d < 15:
                self.off()          # release so next loop can re-arm
            time.sleep(interval)

    # ------------------------------------------------------------------
    #  Resource release
    # ------------------------------------------------------------------

    def close(self):
        """Stop radar thread and release GPIO."""
        self.stop_radar()
        self._gpio.cleanup()
