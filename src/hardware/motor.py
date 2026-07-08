"""Motor control boundary for the Yahboom 4WD car.

Upper-level features such as line tracking or obstacle avoidance should call
this module instead of writing GPIO pins directly.
"""

from src import config


class MotorController:
    """Control the two motor channels through RPi.GPIO."""

    def __init__(self, gpio=None):
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError("RPi.GPIO 只能在树莓派环境中使用") from exc

        self.gpio = gpio
        self._pwm_left = None
        self._pwm_right = None
        self._setup_gpio()

    def forward(self, left_speed, right_speed):
        """前进：左右电机都向前转。"""
        self._drive(
            self.gpio.HIGH,
            self.gpio.LOW,
            self.gpio.HIGH,
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def backward(self, left_speed, right_speed):
        """后退：左右电机都反向转。"""
        self._drive(
            self.gpio.LOW,
            self.gpio.HIGH,
            self.gpio.LOW,
            self.gpio.HIGH,
            left_speed,
            right_speed,
        )

    def left(self, left_speed, right_speed):
        """左转：左电机停，右电机向前转。"""
        self._drive(
            self.gpio.LOW,
            self.gpio.LOW,
            self.gpio.HIGH,
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def right(self, left_speed, right_speed):
        """右转：左电机向前转，右电机停。"""
        self._drive(
            self.gpio.HIGH,
            self.gpio.LOW,
            self.gpio.LOW,
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def spin_left(self, left_speed, right_speed):
        """原地左旋：左电机后退，右电机前进。"""
        self._drive(
            self.gpio.LOW,
            self.gpio.HIGH,
            self.gpio.HIGH,
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def spin_right(self, left_speed, right_speed):
        """原地右旋：左电机前进，右电机后退。"""
        self._drive(
            self.gpio.HIGH,
            self.gpio.LOW,
            self.gpio.LOW,
            self.gpio.HIGH,
            left_speed,
            right_speed,
        )

    def brake(self):
        """停止：方向脚全部拉低，PWM 占空比归零。"""
        self.gpio.output(config.MOTOR_IN1, self.gpio.LOW)
        self.gpio.output(config.MOTOR_IN2, self.gpio.LOW)
        self.gpio.output(config.MOTOR_IN3, self.gpio.LOW)
        self.gpio.output(config.MOTOR_IN4, self.gpio.LOW)
        self._pwm_left.ChangeDutyCycle(0)
        self._pwm_right.ChangeDutyCycle(0)

    def close(self):
        """释放硬件资源；finally 中调用它可以保证异常时也停车。"""
        try:
            self.brake()
        finally:
            self._pwm_left.stop()
            self._pwm_right.stop()
            self.gpio.cleanup()

    def _setup_gpio(self):
        self.gpio.setmode(self.gpio.BCM)
        self.gpio.setwarnings(False)
        self.gpio.setup(config.MOTOR_ENA, self.gpio.OUT, initial=self.gpio.HIGH)
        self.gpio.setup(config.MOTOR_IN1, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_IN2, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_ENB, self.gpio.OUT, initial=self.gpio.HIGH)
        self.gpio.setup(config.MOTOR_IN3, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_IN4, self.gpio.OUT, initial=self.gpio.LOW)

        self._pwm_left = self.gpio.PWM(config.MOTOR_ENA, config.MOTOR_PWM_FREQUENCY)
        self._pwm_right = self.gpio.PWM(config.MOTOR_ENB, config.MOTOR_PWM_FREQUENCY)
        self._pwm_left.start(0)
        self._pwm_right.start(0)

    def _drive(
        self,
        left_forward_pin_value,
        left_backward_pin_value,
        right_forward_pin_value,
        right_backward_pin_value,
        left_speed,
        right_speed,
    ):
        self._validate_speed("left_speed", left_speed)
        self._validate_speed("right_speed", right_speed)

        self.gpio.output(config.MOTOR_IN1, left_forward_pin_value)
        self.gpio.output(config.MOTOR_IN2, left_backward_pin_value)
        self.gpio.output(config.MOTOR_IN3, right_forward_pin_value)
        self.gpio.output(config.MOTOR_IN4, right_backward_pin_value)
        self._pwm_left.ChangeDutyCycle(left_speed)
        self._pwm_right.ChangeDutyCycle(right_speed)

    @staticmethod
    def _validate_speed(name, speed):
        if speed < 0 or speed > 100:
            raise ValueError(f"{name} 必须在 0 到 100 之间")
