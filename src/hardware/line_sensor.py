"""Line tracking sensor boundary.

本模块只负责读取四路红外循迹传感器，不控制电机。
巡线策略和节点判断放在 tasks 层，避免 GPIO 读取和行驶流程耦合。
"""

from dataclasses import dataclass

from src import config


@dataclass(frozen=True)
class LineReading:
    """四路巡线传感器的归一化读数。

    参数说明：
    left_outer: 左1传感器是否检测到黑线。
    left_inner: 左2传感器是否检测到黑线。
    right_inner: 右1传感器是否检测到黑线。
    right_outer: 右2传感器是否检测到黑线。
    """

    left_outer: bool
    left_inner: bool
    right_inner: bool
    right_outer: bool

    @classmethod
    def from_gpio_values(
        cls,
        left_outer_value,
        left_inner_value,
        right_inner_value,
        right_outer_value,
    ):
        """把 GPIO 原始电平转换为“是否检测到黑线”。

        参数说明：
        left_outer_value: 左1传感器 GPIO.input 的原始返回值。
        left_inner_value: 左2传感器 GPIO.input 的原始返回值。
        right_inner_value: 右1传感器 GPIO.input 的原始返回值。
        right_outer_value: 右2传感器 GPIO.input 的原始返回值。
        """
        black_value = config.LINE_SENSOR_BLACK_VALUE
        return cls(
            left_outer=left_outer_value == black_value,
            left_inner=left_inner_value == black_value,
            right_inner=right_inner_value == black_value,
            right_outer=right_outer_value == black_value,
        )


class LineSensor:
    """Read the four line tracking GPIO inputs."""

    def __init__(self, gpio=None):
        """初始化四路巡线传感器输入引脚。

        参数说明：
        gpio: 可选的 GPIO 模块；实机运行时不传，测试时可传入假 GPIO。
        """
        if gpio is None:
            try:
                import RPi.GPIO as gpio
            except ModuleNotFoundError as exc:
                raise RuntimeError("RPi.GPIO 只能在树莓派环境中使用") from exc

        self.gpio = gpio
        self.pins = (
            config.LINE_SENSOR_LEFT_OUTER_PIN,
            config.LINE_SENSOR_LEFT_INNER_PIN,
            config.LINE_SENSOR_RIGHT_INNER_PIN,
            config.LINE_SENSOR_RIGHT_OUTER_PIN,
        )
        self._setup_gpio()

    def read(self):
        """读取一次四路传感器状态。

        返回值：
        LineReading，四个字段均表示对应传感器是否检测到黑线。
        """
        # 读取顺序保持从左到右，便于对照实机打印结果和硬件表。
        return LineReading.from_gpio_values(
            self.gpio.input(config.LINE_SENSOR_LEFT_OUTER_PIN),
            self.gpio.input(config.LINE_SENSOR_LEFT_INNER_PIN),
            self.gpio.input(config.LINE_SENSOR_RIGHT_INNER_PIN),
            self.gpio.input(config.LINE_SENSOR_RIGHT_OUTER_PIN),
        )

    def close(self):
        """释放巡线传感器占用的 GPIO 输入引脚。"""
        self.gpio.cleanup(self.pins)

    def _setup_gpio(self):
        # config.py 中保存的是 BCM 编号，所以这里必须使用 GPIO.BCM。
        self.gpio.setmode(self.gpio.BCM)
        self.gpio.setwarnings(False)

        # 四路传感器都是输入脚，不在这里做任何电机动作。
        for pin in self.pins:
            self.gpio.setup(pin, self.gpio.IN)
