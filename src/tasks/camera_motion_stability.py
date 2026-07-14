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
class MotionPhaseStart:
    """一次运动阶段的开始记录。"""

    name: str
    action: str
    elapsed_seconds: float


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
    detection_mode: Optional[str]
    no_frame_timeout_seconds: float
    last_frame_elapsed_seconds: Optional[float]
    last_frame_phase: Optional[str]
    suspected_trigger_phase: Optional[str]
    stall_detected_elapsed_seconds: Optional[float]
    stall_detected_phase: Optional[str]
    no_frame_seconds_at_detection: Optional[float]
    reader_thread_blocked: bool
    phase_starts: Tuple[MotionPhaseStart, ...]
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
    no_frame_timeout: float = 2.0,
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
        no_frame_timeout: 即使 OpenCV 没返回错误，连续无新帧多久后刹车。
        progress_interval: 正常读帧进度的打印间隔。
        log: 接收一行进度文本的回调函数。

    返回:
        CameraMotionStabilityResult，包含结论、帧数和失败明细。

    分步逻辑:
        1. 后台线程持续读取摄像头，记录瞬时和连续失败。
        2. 主线程依次执行静止、前进、静止、后退和静止阶段。
        3. 主线程独立检查最后成功帧时间，不依赖阻塞中的 OpenCV read()。
        4. 连续失败或无帧超时后立即刹车，并记录最可能的触发阶段。
        5. 汇总为 pass、warning 或 fail 三种结论。
    """

    _validate_parameters(
        speed=speed,
        move_seconds=move_seconds,
        pause_seconds=pause_seconds,
        baseline_seconds=baseline_seconds,
        cycles=cycles,
        failure_threshold=failure_threshold,
        no_frame_timeout=no_frame_timeout,
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
        "detection_mode": None,
        "last_frame_at": None,
        "last_frame_phase": None,
        "suspected_trigger_phase": None,
        "stall_detected_at": None,
        "stall_detected_phase": None,
        "no_frame_seconds_at_detection": None,
    }
    failure_records = []
    phase_records = []

    def monitor_camera() -> None:
        """持续读取摄像头；达到失败阈值后通知主线程停车。"""

        last_progress_at = started_at
        while not stop_monitor.is_set():
            try:
                camera.read_frame(copy=False)
            except CameraCaptureError as exc:
                if stop_monitor.is_set():
                    return
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
                        state["detection_mode"] = "opencv-read-error"
                        state["stall_detected_at"] = now
                        state["stall_detected_phase"] = str(state["phase"])
                        state["suspected_trigger_phase"] = (
                            _infer_suspected_trigger_phase(
                                last_frame_at=state["last_frame_at"],
                                last_frame_phase=state["last_frame_phase"],
                                phase_records=phase_records,
                                started_at=started_at,
                            )
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
                if stop_monitor.is_set():
                    return
                now = time.monotonic()
                with state_lock:
                    state["failure_reason"] = (
                        f"摄像头监测线程异常: {type(exc).__name__}: {exc}"
                    )
                    state["detection_mode"] = "camera-thread-error"
                    state["stall_detected_at"] = now
                    state["stall_detected_phase"] = str(state["phase"])
                    state["suspected_trigger_phase"] = (
                        _infer_suspected_trigger_phase(
                            last_frame_at=state["last_frame_at"],
                            last_frame_phase=state["last_frame_phase"],
                            phase_records=phase_records,
                            started_at=started_at,
                        )
                    )
                log(f"[camera-error] {state['failure_reason']}")
                camera_dropped.set()
                return

            now = time.monotonic()
            if stop_monitor.is_set():
                return
            with state_lock:
                state["frames_read"] += 1
                state["consecutive_failures"] = 0
                phase = str(state["phase"])
                state["last_frame_at"] = now
                state["last_frame_phase"] = phase
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
        # 每段动作期间轮询最后成功帧时间，避免被 OpenCV 的阻塞 read() 拖延。
        for phase_name, action_name, duration in phases:
            phase_started_at = time.monotonic()
            with state_lock:
                state["phase"] = phase_name
                phase_records.append(
                    MotionPhaseStart(
                        name=phase_name,
                        action=action_name,
                        elapsed_seconds=round(phase_started_at - started_at, 3),
                    )
                )

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

            phase_deadline = phase_started_at + duration
            while not camera_dropped.is_set():
                now = time.monotonic()
                with state_lock:
                    last_frame_at = state["last_frame_at"]
                    frame_reference_at = last_frame_at or started_at
                    no_frame_seconds = now - frame_reference_at
                    if no_frame_seconds >= no_frame_timeout:
                        state["failure_reason"] = (
                            f"连续 {no_frame_seconds:.2f} 秒没有收到新画面"
                        )
                        state["detection_mode"] = "no-frame-watchdog"
                        state["stall_detected_at"] = now
                        state["stall_detected_phase"] = phase_name
                        state["no_frame_seconds_at_detection"] = round(
                            no_frame_seconds, 3
                        )
                        state["suspected_trigger_phase"] = (
                            _infer_suspected_trigger_phase(
                                last_frame_at=last_frame_at,
                                last_frame_phase=state["last_frame_phase"],
                                phase_records=phase_records,
                                started_at=started_at,
                            )
                        )
                        stall_details = (
                            state["last_frame_phase"],
                            state["suspected_trigger_phase"],
                        )
                    else:
                        stall_details = None

                if stall_details is not None:
                    # 看门狗运行在主线程，这里不等待摄像头线程即可立即刹车。
                    motor.brake()
                    camera_dropped.set()
                    log(
                        f"[camera-stall] no_frame_for={no_frame_seconds:.2f}s "
                        f"last_frame_phase={stall_details[0]} "
                        f"suspected_trigger_phase={stall_details[1]} "
                        f"detected_phase={phase_name}"
                    )
                    break

                remaining = phase_deadline - now
                if remaining <= 0:
                    break
                camera_dropped.wait(min(0.05, remaining))

            if camera_dropped.is_set():
                motor.brake()
                break

            motor.brake()
            completed_phases += 1
    finally:
        # 不论正常结束、异常或 Ctrl+C，先停车，再结束摄像头监测。
        motor.brake()
        stop_monitor.set()
        # 看门狗触发后只短暂等待，不能让阻塞 read() 延迟测试返回。
        join_timeout = 0.5 if camera_dropped.is_set() else no_frame_timeout
        monitor_thread.join(timeout=join_timeout)

    reader_thread_blocked = monitor_thread.is_alive()
    if reader_thread_blocked and not camera_dropped.is_set():
        camera_dropped.set()
        with state_lock:
            now = time.monotonic()
            state["failure_reason"] = (
                f"测试结束时 OpenCV read() 超过 {no_frame_timeout:.2f} 秒仍未返回"
            )
            state["detection_mode"] = "reader-blocked-at-finish"
            state["stall_detected_at"] = now
            state["stall_detected_phase"] = str(state["phase"])
            state["suspected_trigger_phase"] = _infer_suspected_trigger_phase(
                last_frame_at=state["last_frame_at"],
                last_frame_phase=state["last_frame_phase"],
                phase_records=phase_records,
                started_at=started_at,
            )

    elapsed_seconds = time.monotonic() - started_at
    with state_lock:
        frames_read = int(state["frames_read"])
        read_failures = int(state["read_failures"])
        max_consecutive_failures = int(state["max_consecutive_failures"])
        failure_reason = state["failure_reason"]
        detection_mode = state["detection_mode"]
        last_frame_at = state["last_frame_at"]
        last_frame_phase = state["last_frame_phase"]
        suspected_trigger_phase = state["suspected_trigger_phase"]
        stall_detected_at = state["stall_detected_at"]
        stall_detected_phase = state["stall_detected_phase"]
        no_frame_seconds_at_detection = state["no_frame_seconds_at_detection"]

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
        detection_mode=detection_mode,
        no_frame_timeout_seconds=no_frame_timeout,
        last_frame_elapsed_seconds=(
            None if last_frame_at is None else round(last_frame_at - started_at, 3)
        ),
        last_frame_phase=last_frame_phase,
        suspected_trigger_phase=suspected_trigger_phase,
        stall_detected_elapsed_seconds=(
            None
            if stall_detected_at is None
            else round(stall_detected_at - started_at, 3)
        ),
        stall_detected_phase=stall_detected_phase,
        no_frame_seconds_at_detection=no_frame_seconds_at_detection,
        reader_thread_blocked=reader_thread_blocked,
        phase_starts=tuple(phase_records),
        failures=tuple(failure_records),
    )


def _infer_suspected_trigger_phase(
    *,
    last_frame_at,
    last_frame_phase,
    phase_records,
    started_at: float,
) -> Optional[str]:
    """根据最后成功帧与运动阶段，推测最可能触发停帧的阶段。

    如果最后一帧处于运动阶段，直接返回该阶段；如果最后一帧处于停车
    阶段，则返回随后第一个已经开始的运动阶段。这样能够识别“基线阶段
    最后一帧正常，第一次前进后 OpenCV 一直阻塞”的情况。
    """

    if last_frame_at is None:
        return "camera-startup"

    action_by_phase = {record.name: record.action for record in phase_records}
    if last_frame_phase and action_by_phase.get(last_frame_phase) != "stop":
        return str(last_frame_phase)

    last_frame_elapsed = last_frame_at - started_at
    for record in phase_records:
        if record.elapsed_seconds >= last_frame_elapsed and record.action != "stop":
            return record.name
    return None if last_frame_phase is None else str(last_frame_phase)


def _validate_parameters(
    *,
    speed: float,
    move_seconds: float,
    pause_seconds: float,
    baseline_seconds: float,
    cycles: int,
    failure_threshold: int,
    no_frame_timeout: float,
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
    if no_frame_timeout < 0.5 or no_frame_timeout > 5:
        raise ValueError("no_frame_timeout 必须在 0.5 到 5 秒之间")
    if baseline_seconds < no_frame_timeout:
        raise ValueError("baseline_seconds 不能短于 no_frame_timeout")
    if progress_interval <= 0 or progress_interval > 10:
        raise ValueError("progress_interval 必须大于 0 且不能超过 10 秒")

    total_seconds = baseline_seconds + cycles * (2 * move_seconds + 2 * pause_seconds)
    if total_seconds > 60:
        raise ValueError("为了安全，计划测试总时长不能超过 60 秒")
