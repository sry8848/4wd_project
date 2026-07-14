"""不依赖摄像头或传感器的前进、后退循环任务。"""

from __future__ import annotations

import time
from typing import Callable


def run_forward_backward_cycles(
    *,
    motor,
    speed: float,
    move_seconds: float,
    pause_seconds: float,
    cycles: int,
    log: Callable[[str], None] = print,
) -> None:
    """让小车按前进、停车、后退、停车的顺序循环运行。

    参数:
        motor: 已初始化的电机对象，需提供 forward/backward/brake 方法。
        speed: 左右轮共同使用的 PWM 占空比。
        move_seconds: 每次前进或后退的持续时间。
        pause_seconds: 两次运动之间的停车时间。
        cycles: 前进和后退组合动作的循环次数。
        log: 接收运动阶段文本的输出回调。

    分步逻辑:
        1. 校验速度、单段时间、循环次数和总运行时间。
        2. 每轮依次执行前进、停车、后退和停车。
        3. 正常结束、异常或 Ctrl+C 时都先调用 brake() 停车。
    """

    _validate_parameters(
        speed=speed,
        move_seconds=move_seconds,
        pause_seconds=pause_seconds,
        cycles=cycles,
    )

    try:
        for cycle_index in range(1, cycles + 1):
            _run_motion_phase(
                motor=motor,
                cycle_index=cycle_index,
                action_name="forward",
                speed=speed,
                duration=move_seconds,
                log=log,
            )
            _run_stop_phase(
                motor=motor,
                cycle_index=cycle_index,
                phase_name="forward-stop",
                duration=pause_seconds,
                log=log,
            )
            _run_motion_phase(
                motor=motor,
                cycle_index=cycle_index,
                action_name="backward",
                speed=speed,
                duration=move_seconds,
                log=log,
            )
            _run_stop_phase(
                motor=motor,
                cycle_index=cycle_index,
                phase_name="backward-stop",
                duration=pause_seconds,
                log=log,
            )
    finally:
        motor.brake()


def _run_motion_phase(
    *,
    motor,
    cycle_index: int,
    action_name: str,
    speed: float,
    duration: float,
    log: Callable[[str], None],
) -> None:
    """执行一段限时前进或后退动作。"""

    action = getattr(motor, action_name)
    log(
        f"[motion] cycle={cycle_index} action={action_name} "
        f"duration={duration:.2f}s speed={speed:.1f}"
    )
    action(speed, speed)
    time.sleep(duration)
    motor.brake()


def _run_stop_phase(
    *,
    motor,
    cycle_index: int,
    phase_name: str,
    duration: float,
    log: Callable[[str], None],
) -> None:
    """保持停车状态并等待指定时间。"""

    motor.brake()
    log(
        f"[motion] cycle={cycle_index} action={phase_name} "
        f"duration={duration:.2f}s"
    )
    if duration > 0:
        time.sleep(duration)


def _validate_parameters(
    *,
    speed: float,
    move_seconds: float,
    pause_seconds: float,
    cycles: int,
) -> None:
    """限制实机动作强度和测试总时间。"""

    if speed <= 0 or speed > 60:
        raise ValueError("speed 必须大于 0 且不能超过 60")
    if move_seconds <= 0 or move_seconds > 3:
        raise ValueError("move_seconds 必须大于 0 且不能超过 3 秒")
    if pause_seconds < 0 or pause_seconds > 5:
        raise ValueError("pause_seconds 必须在 0 到 5 秒之间")
    if cycles < 1 or cycles > 10:
        raise ValueError("cycles 必须在 1 到 10 之间")

    total_seconds = cycles * (2 * move_seconds + 2 * pause_seconds)
    if total_seconds > 60:
        raise ValueError("为了安全，计划测试总时长不能超过 60 秒")
