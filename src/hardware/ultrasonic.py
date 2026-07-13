"""Ultrasonic distance sensor and servo scanning module.

Provides two classes:

- UltrasonicSensor — read distance, filter outliers, background monitoring thread.
- UltrasonicServo — mount the sensor on a servo, scan left / front / right,
                     recommend the clearest direction.

Both classes only measure and decide; they never drive the motors.
Upper-layer tasks (obstacle_avoid.py, patrol.py) call these and then
decide what motor action to take.
"""

from src import config
import time
import threading


class UltrasonicSensor:
    """Measure distance with an HC-SR04 (or compatible) ultrasonic module.

    Usage::

        sensor = UltrasonicSensor()
        d = sensor.read_distance()       # single shot
        d = sensor.read_filtered()       # median of several shots
        sensor.start_monitoring()        # background thread
        if sensor.obstacle_detected:
            ...
        sensor.close()
    """

    def __init__(self, gpio=None,
                 trig_pin=None, echo_pin=None,
                 threshold_cm=None, samples=None, timeout_s=None):
        """
        Parameters
        ----------
        gpio : module or None
            Pass a mock GPIO object for testing on non-RPi machines.
            ``None`` (the default) imports ``RPi.GPIO`` at runtime.
        trig_pin, echo_pin : int or None
            BCM pin numbers.  Falls back to ``config.ULTRASONIC_TRIG`` /
            ``config.ULTRASONIC_ECHO``.
        threshold_cm : int
            Distance below which ``obstacle_detected`` becomes ``True``.
        samples : int
            How many valid readings ``read_filtered`` tries to collect.
        timeout_s : float
            Echo pin timeout in seconds (default 0.10 = 100 ms).
        """
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "RPi.GPIO is not available; pass gpio=MockGPIO() for tests"
                ) from exc
        self._gpio = gpio

        self.trig_pin = trig_pin if trig_pin is not None else config.ULTRASONIC_TRIG
        self.echo_pin = echo_pin if echo_pin is not None else config.ULTRASONIC_ECHO
        self.pins = (self.trig_pin, self.echo_pin)
        self.threshold = threshold_cm if threshold_cm is not None else config.ULTRASONIC_THRESHOLD
        self.samples = samples if samples is not None else config.ULTRASONIC_SAMPLES
        self.timeout = timeout_s if timeout_s is not None else config.ULTRASONIC_TIMEOUT

        # Background-monitoring state
        self.obstacle_detected = False
        self.last_distance = -1.0
        self.reading_sequence = 0
        self._monitoring = False
        self._thread = None
        self._lock = threading.Lock()

        self._gpio_init()

    # ------------------------------------------------------------------
    #   GPIO
    # ------------------------------------------------------------------

    def _gpio_init(self):
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setwarnings(False)
        self._gpio.setup(self.trig_pin, self._gpio.OUT, initial=self._gpio.LOW)
        self._gpio.setup(self.echo_pin, self._gpio.IN)
        time.sleep(0.3)

    # ------------------------------------------------------------------
    #   Core ranging
    # ------------------------------------------------------------------

    def read_distance(self):
        """Single distance measurement in centimetres.

        Returns the distance as a ``float``, or ``-1`` on timeout / error.

        Timing diagram::

          Trig  ___|‾‾‾|____              (15 µs pulse)
          Echo       |___________|         (width = round-trip time)
                     ↑ start    ↑ end
        """
        g = self._gpio

        # Send a 15 µs trigger pulse.
        g.output(self.trig_pin, g.LOW)
        time.sleep(0.000002)
        g.output(self.trig_pin, g.HIGH)
        time.sleep(0.000015)
        g.output(self.trig_pin, g.LOW)

        # Wait for Echo to go HIGH (start of echo).
        wait_start = time.time()
        while not g.input(self.echo_pin):
            if time.time() - wait_start > self.timeout:
                return -1

        pulse_start = time.time()

        # Wait for Echo to go LOW (end of echo).
        while g.input(self.echo_pin):
            if time.time() - pulse_start > self.timeout:
                return -1

        pulse_end = time.time()
        duration = pulse_end - pulse_start

        # distance (cm) = duration (s) × speed of sound (cm/s) / 2
        distance_cm = duration * 34000 / 2
        return distance_cm

    def read_filtered(self):
        """Median of several valid readings (more robust than a single shot).

        Returns a ``float`` in cm, or ``-1`` when no valid reading was obtained.
        """
        valid = []
        for _ in range(self.samples + 2):          # sample a little extra
            d = self.read_distance()
            if 0 < d < 500:                         # discard -1, 0, and outliers
                valid.append(d)
            time.sleep(0.01)
            if len(valid) >= self.samples:
                break

        if not valid:
            return -1

        valid.sort()
        return round(valid[len(valid) // 2], 1)

    # ------------------------------------------------------------------
    #   Obstacle predicate
    # ------------------------------------------------------------------

    def is_obstructed(self, distance=None):
        """``True`` when *distance* (cm) is below ``self.threshold``."""
        if distance is None:
            distance = self.read_filtered()
        if distance < 0:
            return False
        return distance < self.threshold

    # ------------------------------------------------------------------
    #   Background monitoring thread
    # ------------------------------------------------------------------

    def _monitor_loop(self):
        """Publish each single distance measurement without batch filtering.

        Each loop performs one trigger/echo measurement, publishes its result
        atomically, then leaves a short gap before the next ultrasonic pulse.
        A ``-1`` timeout remains a non-obstacle reading, matching existing logic.
        """
        while self._monitoring:
            d = self.read_distance()
            with self._lock:
                self.last_distance = d
                self.obstacle_detected = (d > 0 and d < self.threshold)
                self.reading_sequence += 1
            time.sleep(0.06)

    def get_cached_reading(self):
        """Return one atomic background reading snapshot.

        Returns:
        A tuple of ``(sequence, distance_cm, obstacle_detected)``. ``sequence``
        increases only after a complete filtered measurement is published.
        """
        with self._lock:
            return (
                self.reading_sequence,
                self.last_distance,
                self.obstacle_detected,
            )

    def start_monitoring(self):
        """Launch a daemon thread that publishes every single measurement."""
        if self._monitoring:
            return
        self._monitoring = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="ultrasonic-monitor"
        )
        self._thread.start()

    def stop_monitoring(self):
        """Stop the background thread."""
        self._monitoring = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    # ------------------------------------------------------------------
    #   Resource release
    # ------------------------------------------------------------------

    def close(self):
        """Stop monitoring and release GPIO resources."""
        self.stop_monitoring()
        self._gpio.cleanup(self.pins)


class UltrasonicServo:
    """Ultrasonic sensor mounted on a servo for multi-direction scanning.

    Scans right (0°), front (90°), left (180°) and recommends the
    safest direction.

    Usage::

        us = UltrasonicServo()
        distances = us.scan_surroundings()   # -> dict
        best = us.choose_best_direction(distances)
        us.close()

    Servo angle → PWM duty-cycle mapping (50 Hz PWM)::

        0°   →  duty 2.5   (≈ 0.5 ms pulse)
        90°  →  duty 7.5   (≈ 1.5 ms pulse)
        180° →  duty 12.5  (≈ 2.5 ms pulse)
    """

    ANGLE_DUTY = {0: 2.5, 45: 5.0, 90: 7.5, 135: 10.0, 180: 12.5}

    def __init__(self, gpio=None,
                 servo_pin=None,
                 trig_pin=None, echo_pin=None,
                 threshold_cm=None, samples=None):
        """
        Parameters
        ----------
        gpio : module or None
            Mock GPIO or ``RPi.GPIO`` (auto-imported when ``None``).
        servo_pin : int or None
            BCM pin for the servo signal line.  Falls back to
            ``config.SERVO_PIN`` (23).
        trig_pin, echo_pin : int or None
            Forwarded to ``UltrasonicSensor``.
        threshold_cm : int or None
            Obstacle threshold forwarded to ``UltrasonicSensor``.
        samples : int or None
            Samples per direction forwarded to ``UltrasonicSensor``.
        """
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "RPi.GPIO is not available; pass gpio=MockGPIO() for tests"
                ) from exc
        self._gpio = gpio

        self.servo_pin = servo_pin if servo_pin is not None else config.SERVO_PIN
        self.threshold = threshold_cm if threshold_cm is not None else config.ULTRASONIC_THRESHOLD

        # Reuse the sensor class for ranging.
        self.sensor = UltrasonicSensor(
            gpio=gpio,
            trig_pin=trig_pin,
            echo_pin=echo_pin,
            threshold_cm=self.threshold,
            samples=samples,
        )

        # Servo GPIO setup (separate from sensor GPIO).
        self._gpio.setup(self.servo_pin, self._gpio.OUT)
        self._pwm = self._gpio.PWM(self.servo_pin, config.SERVO_PWM_FREQUENCY)
        self._pwm.start(0)
        self._current_angle = 90
        time.sleep(0.3)

        self.distance_map = {"left": -1, "front": -1, "right": -1}

    # ------------------------------------------------------------------
    #   Servo control
    # ------------------------------------------------------------------

    @staticmethod
    def _angle_to_duty(angle):
        """Linear interpolation: 0°→2.5, 90°→7.5, 180°→12.5."""
        a = max(0, min(180, angle))
        if a in UltrasonicServo.ANGLE_DUTY:
            return UltrasonicServo.ANGLE_DUTY[a]
        return round(2.5 + (a / 180.0) * 10.0, 1)

    def set_angle(self, angle, wait_ms=300):
        """Rotate the servo to *angle* (0–180°) and wait for it to settle."""
        a = max(0, min(180, angle))
        self._pwm.ChangeDutyCycle(self._angle_to_duty(a))
        time.sleep(wait_ms / 1000.0)
        self._pwm.ChangeDutyCycle(0)          # remove jitter
        self._current_angle = a

    # ------------------------------------------------------------------
    #   Measure at a given angle
    # ------------------------------------------------------------------

    def measure_at(self, angle):
        """Rotate to *angle*, take one filtered reading, return cm."""
        self.set_angle(angle)
        return self.sensor.read_filtered()

    # ------------------------------------------------------------------
    #   Three-direction scan
    # ------------------------------------------------------------------

    def scan_surroundings(self):
        """Measure right (0°), front (90°), left (180°) and update
        ``self.distance_map``.

        Returns ``{"left": …, "front": …, "right": …}``.
        """
        print("  Scanning  right(0°) …", end=" ")
        self.distance_map["right"] = self.measure_at(0)
        self._print_dist(self.distance_map["right"])

        print("  Scanning  front(90°) …", end=" ")
        self.distance_map["front"] = self.measure_at(90)
        self._print_dist(self.distance_map["front"])

        print("  Scanning  left(180°) …", end=" ")
        self.distance_map["left"] = self.measure_at(180)
        self._print_dist(self.distance_map["left"])

        self.set_angle(90, wait_ms=200)
        return self.distance_map

    @staticmethod
    def _print_dist(d):
        if d > 0:
            print(f"{d:.1f} cm")
        else:
            print("⚠️ timeout")

    # ------------------------------------------------------------------
    #   Direction recommendation
    # ------------------------------------------------------------------

    def choose_best_direction(self, distance_map=None):
        """Return the safest direction based on the scan.

        Returns ``"front"``, ``"left"``, ``"right"``, or ``None``
        (all directions blocked or unknown).
        """
        dm = distance_map if distance_map is not None else self.distance_map

        left = dm.get("left", 500)
        front = dm.get("front", 500)
        right = dm.get("right", 500)

        # Treat timeouts as "wide open" (the sensor may be facing a
        # corridor with no echo return within range).
        if left < 0:
            left = 500
        if front < 0:
            front = 500
        if right < 0:
            right = 500

        if front >= self.threshold:
            return "front"
        if left >= self.threshold and right >= self.threshold:
            return "left" if left >= right else "right"
        if left >= self.threshold:
            return "left"
        if right >= self.threshold:
            return "right"
        return None

    # ------------------------------------------------------------------
    #   Resource release
    # ------------------------------------------------------------------

    def close(self):
        """Stop PWM and release GPIO (including the underlying sensor)."""
        try:
            self._pwm.stop()
        finally:
            self.sensor.close()
