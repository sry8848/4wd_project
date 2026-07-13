"""Line following and node detection task logic."""

from dataclasses import dataclass
import time


ACTION_FORWARD = "forward"
ACTION_LEFT = "left"
ACTION_RIGHT = "right"
ACTION_SEARCH_LEFT = "search_left"
ACTION_NODE = "node"


@dataclass(frozen=True)
class LineStepResult:
    """一次巡线闭环的读数、判断结果和执行动作。

    参数说明：
    reading: 本次四路巡线传感器读数。
    action: 根据读数决定并已执行的电机动作。
    is_node: 本次读数是否满足网格节点判断。
    line_seen: 四路传感器是否至少一路看到黑线。
    centered_line: 内侧两路是否同时看到黑线；当前实车普通边居中主要为全白，
        该字段只描述这一种传感器形态，不作为走边居中的唯一依据。
    """

    reading: object
    action: str
    is_node: bool
    line_seen: bool
    centered_line: bool


def is_at_node(reading):
    """判断当前四路巡线读数是否表示网格节点。

    参数说明：
    reading: src.hardware.line_sensor.LineReading 实例，字段含义为是否检测到黑线。
    """
    # 节点判断需要内侧两路都压到黑线，并且至少一个外侧传感器也压到黑线。
    # 这样不会把普通直线上的“内侧两路黑”误判成十字节点。
    return reading.left_inner and reading.right_inner and (
        reading.left_outer or reading.right_outer
    )


def is_line_seen(reading):
    """判断四路巡线传感器是否至少一路看到黑线。

    参数说明：
    reading: src.hardware.line_sensor.LineReading 实例。
    """
    return (
        reading.left_outer
        or reading.left_inner
        or reading.right_inner
        or reading.right_outer
    )


def is_centered_line(reading):
    """判断内侧两路传感器是否同时看到黑线。

    参数说明：
    reading: src.hardware.line_sensor.LineReading 实例。

    当前实车普通边居中主要为全白；此函数保留给转向找线识别内侧双黑，
    不能单独作为走边居中的定义。
    """
    return reading.left_inner and reading.right_inner


def track_node_check(sensor):
    """读取一次循迹传感器并判断是否到达节点。

    参数说明：
    sensor: 提供 read() 方法的循迹传感器对象，通常是 LineSensor。
    """
    return is_at_node(sensor.read())


def decide_line_action(reading):
    """根据四路巡线读数决定下一步行驶动作。

    参数说明：
    reading: src.hardware.line_sensor.LineReading 实例，字段含义为是否检测到黑线。
    """
    if is_at_node(reading):
        return ACTION_NODE

    # 参考项目逻辑：左内侧压线或左外侧压线时，向左修正。
    if (reading.left_inner and not reading.right_inner) or reading.left_outer:
        return ACTION_LEFT

    # 参考项目逻辑：右内侧压线或右外侧压线时，向右修正。
    if (not reading.left_inner and reading.right_inner) or reading.right_outer:
        return ACTION_RIGHT

    if reading.left_inner and reading.right_inner:
        return ACTION_FORWARD

    return ACTION_SEARCH_LEFT


class LineFollower:
    """Combine a line sensor and motor controller to follow a black line."""

    def __init__(
        self,
        sensor,
        motor,
        forward_speed=20,
        turn_speed=80,
        search_speed=8,
        left_turn_speed=None,
        right_turn_speed=None,
        debug_output=None,
    ):
        """保存循迹任务所需的硬件对象和速度参数。

        参数说明：
        sensor: 提供 read() 方法的循迹传感器对象。
        motor: 提供 forward/left/right/spin_left/brake 方法的电机控制对象。
        forward_speed: 直行时左右电机 PWM 占空比。
        turn_speed: 默认偏航修正时外侧电机 PWM 占空比。
        left_turn_speed: 左修正时右侧电机 PWM 占空比；不传时使用 turn_speed。
        right_turn_speed: 右修正时左侧电机 PWM 占空比；不传时使用 turn_speed。
        search_speed: 丢线后原地左旋搜索的 PWM 占空比。
        debug_output: 可选文本输出流；传入时每轮打印巡线读数、动作和电机命令。
        """
        self.sensor = sensor
        self.motor = motor
        self.forward_speed = forward_speed
        self.turn_speed = turn_speed
        self.left_turn_speed = turn_speed if left_turn_speed is None else left_turn_speed
        self.right_turn_speed = turn_speed if right_turn_speed is None else right_turn_speed
        self.search_speed = search_speed
        self.debug_output = debug_output

    def step(self, forward_on_no_line=False):
        """执行一次“读取传感器 -> 判断动作 -> 控制电机”的循迹步骤。

        参数说明：
        forward_on_no_line: 四路全白时是否直行；仅用于已进入普通边的状态。

        返回值：
        LineStepResult，包含本次读数、动作和节点/线状态。
        """
        reading = self.sensor.read()
        return self.apply_reading(
            reading,
            forward_on_no_line=forward_on_no_line,
        )

    def apply_reading(
        self,
        reading,
        search_left=True,
        forward_on_no_line=False,
    ):
        """根据已读取的传感器结果执行一次巡线动作。

        参数说明：
        reading: src.hardware.line_sensor.LineReading 实例。
        search_left: 四路全白时是否向左找线；False 表示向右找线。
        forward_on_no_line: 四路全白时是否改为直行，优先于 search_left。
        """
        action = decide_line_action(reading)
        if action == ACTION_SEARCH_LEFT and forward_on_no_line:
            action = ACTION_FORWARD

        if action == ACTION_NODE:
            self.motor.brake()
            motor_command = "brake()"
        elif action == ACTION_FORWARD:
            self.motor.forward(self.forward_speed, self.forward_speed)
            motor_command = f"forward({self.forward_speed},{self.forward_speed})"
        elif action == ACTION_LEFT:
            self.motor.left(0, self.left_turn_speed)
            motor_command = f"left(0,{self.left_turn_speed})"
        elif action == ACTION_RIGHT:
            self.motor.right(self.right_turn_speed, 0)
            motor_command = f"right({self.right_turn_speed},0)"
        elif search_left:
            self.motor.spin_left(self.search_speed, self.search_speed)
            motor_command = f"spin_left({self.search_speed},{self.search_speed})"
        else:
            self.motor.spin_right(self.search_speed, self.search_speed)
            motor_command = f"spin_right({self.search_speed},{self.search_speed})"

        if self.debug_output is not None:
            self.debug_output.write(
                "line_debug "
                f"LO={int(reading.left_outer)} "
                f"LI={int(reading.left_inner)} "
                f"RI={int(reading.right_inner)} "
                f"RO={int(reading.right_outer)} "
                f"node={int(action == ACTION_NODE)} "
                f"action={action} "
                f"motor={motor_command}\n"
            )
            self.debug_output.flush()

        return LineStepResult(
            reading=reading,
            action=action,
            is_node=is_at_node(reading),
            line_seen=is_line_seen(reading),
            centered_line=is_centered_line(reading),
        )

    def run_track(self, max_seconds, delay_seconds=0.02):
        """沿黑线行驶，直到到达节点或超时。

        参数说明：
        max_seconds: 最长运行秒数；必须大于 0，防止传感器异常时无限行驶。
        delay_seconds: 每次循迹修正之间的短暂等待时间。
        """
        if max_seconds <= 0:
            raise ValueError("max_seconds 必须大于 0")

        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            result = self.step()
            if result.is_node:
                return True
            time.sleep(delay_seconds)

        self.motor.brake()
        return False
