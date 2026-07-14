"""在小车运动期间连续监测摄像头读帧稳定性。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock, Thread
import time
from typing import Callable, Optional, Tuple

from src.hardware.camera import CameraCaptureError


@dataclass(frozen=True)
class CameraReadFailure:
    """一次摄像头读帧失败记录。

    参数:
        elapsed_seconds: 从测试开始到失败发生的秒数。
        phase: 失败时小车所处的运动阶段。
        consecutive_failures: 当前连续失败次数。
        message: 摄像头层返回的错误信息。
    """

    elapsed_seconds: float
    phase: str
    consecutive_failures: int
    message: str


@dataclass(frozen=True)
class CameraMotionStabilityResult:
    """运动中摄像头稳定性测试结果。"""

    verdict: str
    elapsed_seconds: float
    frames_read: int
    read_failures: int
    max_consecutive_failures: int
    completed_phases: int
    stopped_early: bool
    failure_reason: Optional[str]
    failures: Tuple[CameraReadFailure, ...]


def run_camera_motion_stability_test(
    *,
    motor,
    camera,
    speed: float,
    move_seconds: float,
    pause_seconds: float,
    baseline_seconds: float,
    cycles: int,
    failure_threshold: int = 3,
    progress_interval: float = 1.0,
    log: Callable[[str], None] = print,
) -> CameraMotionStabilityResult:
    """边运动边读帧，并在摄像头连续失败时立即停车。

    参数:
        motor: 已初始化的电机对象，需提供 forward/backward/brake 方法。
        camera: 已打开的摄像头会话，需提供 read_frame 方法。
        speed: 左右轮共同使用的 PWM 占空比。
        move_seconds: 每次前进或后退持续时间。
        pause_seconds: 相邻运动动作之间的停车观察时间。
        baseline_seconds: 首次运动前的静止监测时间。
        cycles: 前进和后退组合动作的重复次数。
        failure_threshold: 判为掉线所需的连续读帧失败次数。
        progress_interval: 正常读帧进度的打印间隔。
        log: 接收一行进度文本的回调函数。

    返回:
        CameraMotionStabilityResult，包含结论、帧数和失败明细。

    分步逻辑:
        1. 后台线程持续读取摄像头，记录瞬时和连续失败。
        2. 主线程依次执行静止、前进、静止、后退和静止阶段。
        3. 连续失败达到阈值时设置停止信号，主线程立即刹车。
        4. 汇总为 pass、warning 或 fail 三种结论。
    """

    _validate_parameters(
        speed=speed,
        move_seconds=move_seconds,
        pause_seconds=pause_seconds,
        baseline_seconds=baseline_seconds,
        cycles=cycles,
        failure_threshold=failure_threshold,
        progress_interval=progress_interval,
    )

    phases = [("baseline-stop", "stop", baseline_seconds)]
    for cycle_index in range(1, cycles + 1):
        phases.extend(
            (
                (f"cycle-{cycle_index}-forward", "forward", move_seconds),
                (f"cycle-{cycle_index}-forward-stop", "stop", pause_seconds),
                (f"cycle-{cycle_index}-backward", "backward", move_seconds),
                (f"cycle-{cycle_index}-backward-stop", "stop", pause_seconds),
            )
        )

    stop_monitor = Event()
    camera_dropped = Event()
    state_lock = Lock()
    started_at = time.monotonic()
    state = {
        "phase": "camera-startup",
        "frames_read": 0,
        "read_failures": 0,
        "consecutive_failures": 0,
        "max_consecutive_failures": 0,
        "failure_reason": None,
    }
    failure_records = []

    def monitor_camera() -> None:
        """持续读取摄像头；达到失败阈值后通知主线程停车。"""

        last_progress_at = started_at
        while not stop_monitor.is_set():
            try:
                camera.read_frame(copy=False)
            except CameraCaptureError as exc:
                now = time.monotonic()
                with state_lock:
                    state["read_failures"] += 1
                    state["consecutive_failures"] += 1
                    state["max_consecutive_failures"] = max(
                        state["max_consecutive_failures"],
                        state["consecutive_failures"],
                    )
                    failure = CameraReadFailure(
                        elapsed_seconds=round(now - started_at, 3),
                        phase=str(state["phase"]),
                        consecutive_failures=int(state["consecutive_failures"]),
                        message=str(exc),
                    )
                    failure_records.append(failure)
                    reached_threshold = (
                        state["consecutive_failures"] >= failure_threshold
                    )
                    if reached_threshold:
                        state["failure_reason"] = (
                            f"摄像头连续 {state['consecutive_failures']} 次读帧失败"
                        )
                log(
                    f"[camera-error] phase={failure.phase} "
                    f"consecutive={failure.consecutive_failures} "
                    f"message={failure.message}"
                )
                if reached_threshold:
                    camera_dropped.set()
                    return
                continue
            except Exception as exc:  # 防止未知摄像头异常让电机继续运动。
                with state_lock:
                    state["failure_reason"] = (
                        f"摄像头监测线程异常: {type(exc).__name__}: {exc}"
                    )
                log(f"[camera-error] {state['failure_reason']}")
                camera_dropped.set()
                return

            now = time.monotonic()
            with state_lock:
                state["frames_read"] += 1
                state["consecutive_failures"] = 0
                phase = str(state["phase"])
                frames_read = int(state["frames_read"])
                read_failures = int(state["read_failures"])
            if now - last_progress_at >= progress_interval:
                log(
                    f"[camera-ok] phase={phase} frames={frames_read} "
                    f"read_failures={read_failures}"
                )
                last_progress_at = now

    monitor_thread = Thread(
        target=monitor_camera,
        name="camera-motion-stability-monitor",
        daemon=True,
    )
    monitor_thread.start()

    completed_phases = 0
    try:
        # 每段运动都使用 Event.wait，使摄像头掉线后无需等完整段落即可停车。
        for phase_name, action_name, duration in phases:
            with state_lock:
                state["phase"] = phase_name

            if action_name == "forward":
                motor.forward(speed, speed)
            elif action_name == "backward":
                motor.backward(speed, speed)
            else:
                motor.brake()

            log(
                f"[motion] phase={phase_name} action={action_name} "
                f"duration={duration:.2f}s speed={speed:.1f}"
            )
            if camera_dropped.wait(duration):
                break

            motor.brake()
            completed_phases += 1
    finally:
        # 不论正常结束、异常或 Ctrl+C，先停车，再结束摄像头监测。
        motor.brake()
        stop_monitor.set()
        monitor_thread.join(timeout=3.0)

    if monitor_thread.is_alive():
        camera_dropped.set()
        with state_lock:
            state["failure_reason"] = "摄像头读取超过 3 秒仍未返回"

    elapsed_seconds = time.monotonic() - started_at
    with state_lock:
        frames_read = int(state["frames_read"])
        read_failures = int(state["read_failures"])
        max_consecutive_failures = int(state["max_consecutive_failures"])
        failure_reason = state["failure_reason"]

    stopped_early = camera_dropped.is_set() or completed_phases < len(phases)
    if stopped_early:
        verdict = "fail"
    elif read_failures:
        verdict = "warning"
    else:
        verdict = "pass"

    return CameraMotionStabilityResult(
        verdict=verdict,
        elapsed_seconds=round(elapsed_seconds, 3),
        frames_read=frames_read,
        read_failures=read_failures,
        max_consecutive_failures=max_consecutive_failures,
        completed_phases=completed_phases,
        stopped_early=stopped_early,
        failure_reason=failure_reason,
        failures=tuple(failure_records),
    )


def _validate_parameters(
    *,
    speed: float,
    move_seconds: float,
    pause_seconds: float,
    baseline_seconds: float,
    cycles: int,
    failure_threshold: int,
    progress_interval: float,
) -> None:
    """校验实机测试参数，限制单段动作和总测试时长。"""

    if speed <= 0 or speed > 60:
        raise ValueError("speed 必须大于 0 且不能超过 60")
    if move_seconds <= 0 or move_seconds > 3:
        raise ValueError("move_seconds 必须大于 0 且不能超过 3 秒")
    if pause_seconds < 0 or pause_seconds > 5:
        raise ValueError("pause_seconds 必须在 0 到 5 秒之间")
    if baseline_seconds < 1 or baseline_seconds > 10:
        raise ValueError("baseline_seconds 必须在 1 到 10 秒之间")
    if cycles < 1 or cycles > 10:
        raise ValueError("cycles 必须在 1 到 10 之间")
    if failure_threshold < 1 or failure_threshold > 10:
        raise ValueError("failure_threshold 必须在 1 到 10 之间")
    if progress_interval <= 0 or progress_interval > 10:
        raise ValueError("progress_interval 必须大于 0 且不能超过 10 秒")

    total_seconds = baseline_seconds + cycles * (2 * move_seconds + 2 * pause_seconds)
    if total_seconds > 60:
        raise ValueError("为了安全，计划测试总时长不能超过 60 秒")
