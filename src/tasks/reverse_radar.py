"""Reverse-radar task: beep urgency proportional to distance.

Combines ``UltrasonicSensor`` and ``Buzzer`` to produce the classic
"closer = faster" warning sound, useful for obstacle-avoidance demos.

This is a **task** — it owns the scheduling logic.  The individual
hardware modules only know how to measure distance (ultrasonic) or
make a sound (buzzer); this layer decides when and why.

Usage::

    from src.tasks.reverse_radar import ReverseRadar

    radar = ReverseRadar()
    radar.radar_beep(35)          # manual one-shot
    radar.start()                 # background thread
    radar.stop()
    radar.close()
"""

import time
import threading


class CachedReverseRadar:
    """Non-blocking beeper driven by a cached ultrasonic distance.

    Parameters:
    source: Object with a ``last_distance`` attribute updated elsewhere.
    buzzer: Buzzer-like object with on()/off().
    time_fn: Monotonic time function, injectable for tests.
    """

    def __init__(self, source, buzzer, time_fn=None):
        self.source = source
        self.buzzer = buzzer
        self._time = time_fn if time_fn is not None else time.monotonic
        self._next_beep_at = 0.0
        self._tone_until = 0.0
        self._active = False

    def tick(self):
        """Update the buzzer once without blocking or measuring distance."""
        distance = getattr(self.source, "last_distance", -1)
        if distance < 0 or distance > 100:
            self.stop()
            return

        if distance <= 15:
            self.buzzer.on()
            self._active = True
            self._tone_until = 0.0
            return

        now = self._time()
        period, on_seconds = self._beep_pattern(distance)
        if now >= self._next_beep_at:
            self.buzzer.on()
            self._active = True
            self._tone_until = now + on_seconds
            self._next_beep_at = now + period
            return

        if self._active and now >= self._tone_until:
            self.buzzer.off()
            self._active = False

    def stop(self):
        """Silence the buzzer and reset the next warning pulse."""
        if self._active:
            self.buzzer.off()
        self._active = False
        self._tone_until = 0.0
        self._next_beep_at = 0.0

    @staticmethod
    def _beep_pattern(distance):
        if distance > 50:
            return 1.1, 0.1
        if distance > 30:
            return 0.6, 0.1
        return 0.3, 0.08


class ReverseRadar:
    """Beep at a rate inversely proportional to distance.

    Parameters
    ----------
    buzzer : Buzzer or None
        Buzzer instance.  Created automatically if ``None``.
    sensor : UltrasonicSensor or None
        Sensor instance.  Created automatically if ``None``.
    """

    def __init__(self, buzzer=None, sensor=None):
        if buzzer is None:
            from src.hardware.buzzer import Buzzer
            buzzer = Buzzer()
        if sensor is None:
            from src.hardware.ultrasonic import UltrasonicSensor
            sensor = UltrasonicSensor()

        self.buzzer = buzzer
        self.sensor = sensor

        # Background-thread state.
        self._looping = False
        self._thread = None

    # ------------------------------------------------------------------
    #  Core: one-shot beep
    # ------------------------------------------------------------------

    def radar_beep(self, distance_cm):
        """One beep whose urgency matches *distance_cm*.

        Call this from a loop::

            while True:
                d = sensor.read_filtered()
                radar.radar_beep(d)
                time.sleep(0.05)

        The method blocks for a silent pause proportional to the
        distance, so the calling loop paces itself naturally.

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

        b = self.buzzer
        if distance_cm > 50:          # far — slow
            b.beep(0.1)
            time.sleep(1.0)
        elif distance_cm > 30:        # medium
            b.beep(0.1)
            time.sleep(0.5)
        elif distance_cm > 15:        # close — quick
            b.beep(0.08)
            time.sleep(0.2)
        else:                          # very close — continuous
            b.on()
            time.sleep(0.1)

    # ------------------------------------------------------------------
    #  Background loop
    # ------------------------------------------------------------------

    def start(self, interval=0.05):
        """Run the radar loop in a background daemon thread.

        Parameters
        ----------
        interval : float
            Seconds between distance readings.
        """
        if self._looping:
            return
        self._looping = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval,),
            daemon=True,
            name="reverse-radar",
        )
        self._thread.start()

    def stop(self):
        """Stop the background thread and silence the buzzer."""
        self._looping = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self.buzzer.off()

    def _loop(self, interval):
        while self._looping:
            d = self.sensor.read_filtered()
            self.radar_beep(d)
            if 0 < d < 15:
                self.buzzer.off()     # release so next loop can re-arm
            time.sleep(interval)

    # ------------------------------------------------------------------
    #  Resource release
    # ------------------------------------------------------------------

    def close(self):
        """Stop the thread and release all hardware resources."""
        self.stop()
        try:
            self.buzzer.close()
        finally:
            self.sensor.close()
