"""Create and own the real grid-navigation hardware stack."""

from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any, Optional

from src.hardware.buzzer import Buzzer
from src.hardware.line_sensor import LineSensor
from src.hardware.motor import MotorController
from src.hardware.ultrasonic import UltrasonicSensor
from src.tasks.edge_follow import CachedObstacleSensor, EdgeFollower
from src.tasks.grid_navigation import GridNavigator
from src.tasks.line_follow import LineFollower
from src.tasks.reverse_radar import CachedReverseRadar


@dataclass
class GridNavigationHardware:
    """Own one real navigator and every hardware resource it depends on.

    参数说明：
    navigator: 已组装的网格导航器。
    motor: 导航器使用的电机控制器。
    line_sensor: 导航器使用的巡线传感器。
    ultrasonic: 可选超声波传感器。
    buzzer: 可选倒车提示蜂鸣器。
    reverse_radar: 可选倒车雷达任务。
    """

    navigator: GridNavigator
    motor: MotorController
    line_sensor: LineSensor
    ultrasonic: Optional[UltrasonicSensor] = None
    buzzer: Optional[Buzzer] = None
    reverse_radar: Optional[CachedReverseRadar] = None
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self):
        """停车并按资源依赖顺序释放整组真实导航硬件。

        分步逻辑：
        1. 先刹车并停止倒车提示。
        2. 停止超声波后台线程并关闭各硬件自己的 GPIO。
        3. 重复调用时不重复释放资源。
        """
        if self._closed:
            return
        self._closed = True

        # ExitStack 会在某个 close() 抛错后继续执行其余清理回调。
        with ExitStack() as cleanup:
            cleanup.callback(self.motor.close)
            cleanup.callback(self.line_sensor.close)
            if self.ultrasonic is not None:
                cleanup.callback(self.ultrasonic.close)
            if self.buzzer is not None:
                cleanup.callback(self.buzzer.close)
            if self.reverse_radar is not None:
                cleanup.callback(self.reverse_radar.stop)
            cleanup.callback(self.motor.brake)


def create_grid_navigation_hardware(
    grid,
    *,
    static_blocked_edges=None,
    forward_speed=20,
    line_turn_speed=80,
    line_left_turn_speed=80,
    line_right_turn_speed=100,
    search_speed=5,
    spin_speed=30,
    left_turn_rough_seconds=0.4,
    right_turn_rough_seconds=0.3,
    uturn_rough_seconds=0.8,
    turn_acquire_timeout=5.0,
    leave_node_min_seconds=0.25,
    node_clear_samples=3,
    node_confirm_samples=1,
    node_center_seconds=0.08,
    obstacle_confirm_samples=1,
    line_acquire_timeout=3.0,
    line_lost_timeout=5.0,
    reverse_speed=15,
    reverse_turn_speed=20,
    edge_max_seconds=20,
    recovery_max_seconds=8,
    delay_seconds=0.02,
    ultrasonic_enabled=True,
    ultrasonic_threshold_cm=20,
    reverse_radar_enabled=True,
    line_debug_output: Optional[Any] = None,
    debug_fn=None,
):
    """创建真实网格导航器及其硬件资源所有者。

    参数说明：
    grid: GridNavigator 使用的可通行网格。
    static_blocked_edges: 启动时已知的封锁边。
    其余运动参数直接传给现有 LineFollower、EdgeFollower 和 GridNavigator。
    ultrasonic_enabled: 是否创建并启动超声波后台监测。
    reverse_radar_enabled: 启用超声波时是否同时创建倒车蜂鸣提示。

    分步逻辑：
    1. 创建电机和巡线传感器。
    2. 按开关创建超声波、蜂鸣器及倒车雷达。
    3. 组装现有巡线、边执行和网格导航对象。
    4. 中途失败时释放已经成功创建的资源。
    """
    with ExitStack() as cleanup:
        motor = MotorController()
        cleanup.callback(motor.close)
        cleanup.callback(motor.brake)

        line_sensor = LineSensor()
        cleanup.callback(line_sensor.close)

        ultrasonic = None
        buzzer = None
        reverse_radar = None
        obstacle_sensor = None
        if ultrasonic_enabled:
            ultrasonic = UltrasonicSensor(threshold_cm=ultrasonic_threshold_cm)
            cleanup.callback(ultrasonic.close)
            ultrasonic.start_monitoring()
            obstacle_sensor = CachedObstacleSensor(ultrasonic)

            if reverse_radar_enabled:
                buzzer = Buzzer()
                cleanup.callback(buzzer.close)
                reverse_radar = CachedReverseRadar(ultrasonic, buzzer)
                cleanup.callback(reverse_radar.stop)

        line_follower = LineFollower(
            line_sensor,
            motor,
            forward_speed=forward_speed,
            turn_speed=line_turn_speed,
            left_turn_speed=line_left_turn_speed,
            right_turn_speed=line_right_turn_speed,
            search_speed=search_speed,
            debug_output=line_debug_output,
        )
        edge_follower = EdgeFollower(
            line_follower,
            obstacle_sensor=obstacle_sensor,
            turn_speed=spin_speed,
            left_turn_rough_seconds=left_turn_rough_seconds,
            right_turn_rough_seconds=right_turn_rough_seconds,
            uturn_rough_seconds=uturn_rough_seconds,
            turn_acquire_timeout=turn_acquire_timeout,
            leave_node_min_seconds=leave_node_min_seconds,
            node_clear_samples=node_clear_samples,
            node_confirm_samples=node_confirm_samples,
            node_center_seconds=node_center_seconds,
            obstacle_confirm_samples=obstacle_confirm_samples,
            line_acquire_timeout=line_acquire_timeout,
            line_lost_timeout=line_lost_timeout,
            reverse_speed=reverse_speed,
            reverse_turn_speed=reverse_turn_speed,
            reverse_radar=reverse_radar,
            delay_seconds=delay_seconds,
            debug_fn=debug_fn,
        )
        navigator = GridNavigator(
            grid,
            edge_follower,
            motor,
            static_blocked_edges=static_blocked_edges,
            edge_max_seconds=edge_max_seconds,
            recovery_max_seconds=recovery_max_seconds,
            debug_fn=debug_fn,
        )

        hardware = GridNavigationHardware(
            navigator=navigator,
            motor=motor,
            line_sensor=line_sensor,
            ultrasonic=ultrasonic,
            buzzer=buzzer,
            reverse_radar=reverse_radar,
        )
        cleanup.pop_all()
        return hardware
