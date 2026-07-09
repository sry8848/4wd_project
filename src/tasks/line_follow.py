"""Line following and node detection task logic."""

import time


ACTION_FORWARD = "forward"
ACTION_LEFT = "left"
ACTION_RIGHT = "right"
ACTION_SEARCH_LEFT = "search_left"
ACTION_NODE = "node"


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
        """
        self.sensor = sensor
        self.motor = motor
        self.forward_speed = forward_speed
        self.turn_speed = turn_speed
        self.left_turn_speed = turn_speed if left_turn_speed is None else left_turn_speed
        self.right_turn_speed = turn_speed if right_turn_speed is None else right_turn_speed
        self.search_speed = search_speed

    def step(self):
        """执行一次“读取传感器 -> 判断动作 -> 控制电机”的循迹步骤。

        返回值：
        本次执行的动作字符串，便于上层记录和测试。
        """
        reading = self.sensor.read()
        action = decide_line_action(reading)

        if action == ACTION_NODE:
            self.motor.brake()
        elif action == ACTION_FORWARD:
            self.motor.forward(self.forward_speed, self.forward_speed)
        elif action == ACTION_LEFT:
            self.motor.left(0, self.left_turn_speed)
        elif action == ACTION_RIGHT:
            self.motor.right(self.right_turn_speed, 0)
        else:
            self.motor.spin_left(self.search_speed, self.search_speed)

        return action

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
            action = self.step()
            if action == ACTION_NODE:
                return True
            time.sleep(delay_seconds)

        self.motor.brake()
        return False
