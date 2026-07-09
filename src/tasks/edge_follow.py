"""Execute one grid edge with line following and obstacle checks."""

import time

from src.tasks.line_follow import ACTION_NODE, is_at_node


EDGE_REACHED_NODE = "reached_node"
EDGE_BLOCKED_BEFORE_ENTERING = "blocked_before_entering"
EDGE_BLOCKED_MID_EDGE = "blocked_mid_edge"
EDGE_TIMEOUT = "timeout"
EDGE_RECOVERED = "recovered"
EDGE_RECOVERY_FAILED = "recovery_failed"


class EdgeFollower:
    """执行“从当前节点到相邻节点”的一条网格边。

    参数说明：
    line_follower: 基础巡线对象，提供 step()、run_track()、sensor、motor。
    obstacle_sensor: 可选超声波对象，提供 is_obstructed()；None 表示不做障碍检测。
    turn_speed: 原地掉头时左右电机 PWM 占空比。
    uturn_seconds: 原地掉头持续秒数。
    delay_seconds: 巡线循环等待秒数。
    time_fn/sleep_fn: 时间函数，实机默认使用 time，测试可注入可控时钟。
    """

    def __init__(
        self,
        line_follower,
        obstacle_sensor=None,
        turn_speed=30,
        uturn_seconds=1.2,
        delay_seconds=0.02,
        time_fn=None,
        sleep_fn=None,
    ):
        self.line_follower = line_follower
        self.motor = line_follower.motor
        self.obstacle_sensor = obstacle_sensor
        self.turn_speed = turn_speed
        self.uturn_seconds = uturn_seconds
        self.delay_seconds = delay_seconds
        self._time = time_fn if time_fn is not None else time.monotonic
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep

    def follow_edge(self, max_seconds):
        """沿当前朝向执行一条边，返回边执行状态。

        参数说明：
        max_seconds: 这条边允许消耗的最长时间，必须大于 0。
        """
        if max_seconds <= 0:
            raise ValueError("max_seconds 必须大于 0")

        if self._is_obstructed():
            self.motor.brake()
            return EDGE_BLOCKED_BEFORE_ENTERING

        deadline = self._time() + max_seconds
        if not self._leave_current_node(deadline):
            self.motor.brake()
            return EDGE_TIMEOUT

        while self._time() < deadline:
            if self._is_obstructed():
                self.motor.brake()
                return EDGE_BLOCKED_MID_EDGE

            action = self.line_follower.step()
            if action == ACTION_NODE:
                return EDGE_REACHED_NODE

            self._sleep(self.delay_seconds)

        self.motor.brake()
        return EDGE_TIMEOUT

    def recover_to_start_node(self, max_seconds):
        """中途遇障碍后，掉头并正向巡线回到本条边的起点节点。

        参数说明：
        max_seconds: 回到起点节点允许消耗的最长时间，必须大于 0。
        """
        if max_seconds <= 0:
            raise ValueError("max_seconds 必须大于 0")

        self._turn_around()
        reached_start = self.line_follower.run_track(
            max_seconds=max_seconds,
            delay_seconds=self.delay_seconds,
        )
        if not reached_start:
            self.motor.brake()
            return EDGE_RECOVERY_FAILED

        self._turn_around()
        self.motor.brake()
        return EDGE_RECOVERED

    def _leave_current_node(self, deadline):
        while self._time() < deadline:
            if not is_at_node(self.line_follower.sensor.read()):
                return True

            self.motor.forward(
                self.line_follower.forward_speed,
                self.line_follower.forward_speed,
            )
            self._sleep(self.delay_seconds)

        return False

    def _is_obstructed(self):
        return (
            self.obstacle_sensor is not None
            and self.obstacle_sensor.is_obstructed()
        )

    def _turn_around(self):
        self.motor.spin_left(self.turn_speed, self.turn_speed)
        self._sleep(self.uturn_seconds)
        self.motor.brake()
