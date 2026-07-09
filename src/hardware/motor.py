"""Motor control boundary for the Yahboom 4WD car.

Upper-level features such as line tracking or obstacle avoidance should call
this module instead of writing GPIO pins directly.

给新手看的修改原则：
- 只想调快慢：改运行命令里的 --speed，不要改这里。
- 只想调测试时长：改运行命令里的 --duration，不要改这里。
- 某个动作方向反了：只改对应动作方法里的 HIGH/LOW 组合。
- 不要在循迹、避障等上层功能里直接 GPIO.output 电机引脚。
"""

from src import config


class MotorController:
    """Control the two motor channels through RPi.GPIO."""

    def __init__(self, gpio=None):
        # 实机运行时不传 gpio，会自动导入树莓派上的 RPi.GPIO。
        # 这里保留 gpio 参数，是为了以后需要时可以用假 GPIO 做调试，不影响实机用法。
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError("RPi.GPIO 只能在树莓派环境中使用") from exc

        self.gpio = gpio
        self._pwm_left = None
        self._pwm_right = None
        self.pins = (
            config.MOTOR_ENA,
            config.MOTOR_IN1,
            config.MOTOR_IN2,
            config.MOTOR_ENB,
            config.MOTOR_IN3,
            config.MOTOR_IN4,
        )
        self._setup_gpio()

    def forward(self, left_speed, right_speed):
        """前进：左右电机都向前转。

        如果实机测试发现 forward 变成后退，优先改这里和 backward 的方向脚组合。
        """
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
        """左转：左电机停，右电机向前转。

        这是普通转弯，不是原地旋转；小车会向左偏转前进。
        """
        self._drive(
            self.gpio.LOW,
            self.gpio.LOW,
            self.gpio.HIGH,
            self.gpio.LOW,
            left_speed,
            right_speed,
        )

    def right(self, left_speed, right_speed):
        """右转：左电机向前转，右电机停。

        如果 left/right 效果相反，优先检查左右电机接线或这两个方法的方向组合。
        """
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
        # 先把四个方向脚都拉低，再把 PWM 降到 0，确保两侧电机都停。
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
            # stop() 停止 PWM 输出，cleanup() 释放本程序占用过的 GPIO 状态。
            self._pwm_left.stop()
            self._pwm_right.stop()
            self.gpio.cleanup(self.pins)

    def _setup_gpio(self):
        # config.py 中保存的是 BCM 编号，所以这里必须使用 GPIO.BCM。
        self.gpio.setmode(self.gpio.BCM)
        self.gpio.setwarnings(False)

        # 初始方向脚全部 LOW，避免程序启动瞬间小车误动作。
        self.gpio.setup(config.MOTOR_ENA, self.gpio.OUT, initial=self.gpio.HIGH)
        self.gpio.setup(config.MOTOR_IN1, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_IN2, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_ENB, self.gpio.OUT, initial=self.gpio.HIGH)
        self.gpio.setup(config.MOTOR_IN3, self.gpio.OUT, initial=self.gpio.LOW)
        self.gpio.setup(config.MOTOR_IN4, self.gpio.OUT, initial=self.gpio.LOW)

        # PWM 初始占空比为 0：硬件已初始化，但电机不会立刻转。
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
        # 速度是 PWM 占空比。0 表示不转，100 表示满占空比。
        self._validate_speed("left_speed", left_speed)
        self._validate_speed("right_speed", right_speed)

        # 统一从这里输出方向脚和速度，方便以后排查“某个动作方向不对”的问题。
        self.gpio.output(config.MOTOR_IN1, left_forward_pin_value)
        self.gpio.output(config.MOTOR_IN2, left_backward_pin_value)
        self.gpio.output(config.MOTOR_IN3, right_forward_pin_value)
        self.gpio.output(config.MOTOR_IN4, right_backward_pin_value)
        self._pwm_left.ChangeDutyCycle(left_speed)
        self._pwm_right.ChangeDutyCycle(right_speed)

    @staticmethod
    def _validate_speed(name, speed):
        # RPi.GPIO.PWM.ChangeDutyCycle 的合法范围是 0 到 100，越界说明调用方传错参数。
        if speed < 0 or speed > 100:
            raise ValueError(f"{name} 必须在 0 到 100 之间")
