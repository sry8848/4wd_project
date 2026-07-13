"""二维码自动扫描任务：停车识别，并用底盘短时转向扩大视野。"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Optional, Tuple

from src.algorithms.qr_detect import (
    QRCodeFormatError,
    QRCodePayload,
    parse_qr_payload,
)


@dataclass(frozen=True)
class QRScanResult:
    """自动扫描结果。

    参数：
        payload: 成功识别的结构化内容；超时时为 None。
        frames_scanned: 本次交给识别器处理的总帧数。
        invalid_texts: 解码成功但格式不符合 TYPE:ID 的文本。
        elapsed_seconds: 任务实际运行时间。
        turn_count: 已执行的短时转向次数。
    """

    payload: Optional[QRCodePayload]
    frames_scanned: int
    invalid_texts: Tuple[str, ...]
    elapsed_seconds: float
    turn_count: int


class QRCodeAutoScanner:
    """组合摄像头、二维码算法和电机执行自动视野扫描。

    参数：
        camera: 已打开并提供 read_frame() 的摄像头对象。
        motor: 已初始化的 MotorController 兼容对象。
        recognizer: 提供 decode(frame) 的二维码识别器。
        time_fn: 单调时钟函数，默认使用 time.monotonic。
        sleep_fn: 等待函数，默认使用 time.sleep。

    资源所有权仍由入口层负责；本任务不会 close 摄像头或电机，但所有
    正常、超时和异常路径都会先调用 brake()。
    """

    def __init__(
        self,
        camera,
        motor,
        recognizer,
        *,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.camera = camera
        self.motor = motor
        self.recognizer = recognizer
        self._time = time_fn
        self._sleep = sleep_fn

    def scan(
        self,
        *,
        timeout_seconds: float = 30.0,
        turn_speed: int = 20,
        turn_pulse_seconds: float = 0.12,
        settle_seconds: float = 0.35,
        scan_window_seconds: float = 0.6,
        sweep_half_steps: int = 6,
        progress_fn: Optional[Callable[[str], None]] = None,
    ) -> QRScanResult:
        """限时左右扫视，返回第一个符合 ``TYPE:ID`` 的二维码。

        参数：
            timeout_seconds: 整个任务的最长运行时间。
            turn_speed: 原地转向的左右轮 PWM 占空比。
            turn_pulse_seconds: 每次短时转向的持续时间。
            settle_seconds: 停车后等待画面稳定的时间。
            scan_window_seconds: 每个停车位置连续识别的时间。
            sweep_half_steps: 从中间方向转到一侧的大致步数。
            progress_fn: 可选进度输出回调。
        """

        self._validate_parameters(
            timeout_seconds=timeout_seconds,
            turn_speed=turn_speed,
            turn_pulse_seconds=turn_pulse_seconds,
            settle_seconds=settle_seconds,
            scan_window_seconds=scan_window_seconds,
            sweep_half_steps=sweep_half_steps,
        )

        started_at = self._time()
        deadline = started_at + timeout_seconds
        frames_scanned = 0
        turn_count = 0
        invalid_texts = []

        # 从车头中间开始：右侧边界 -> 左侧边界 -> 回到中间，循环扫视。
        sweep = (
            [("right", sweep_half_steps)]
            + [("left", sweep_half_steps * 2)]
            + [("right", sweep_half_steps)]
        )

        try:
            self.motor.brake()
            while self._time() < deadline:
                for direction, step_count in sweep:
                    for _ in range(step_count):
                        # 1. 停车状态连续读取多帧，避免只碰到模糊或曝光未稳的一帧。
                        payload, scanned, invalid = self._scan_stationary(
                            deadline=min(
                                deadline,
                                self._time() + scan_window_seconds,
                            )
                        )
                        frames_scanned += scanned
                        for text in invalid:
                            if text not in invalid_texts:
                                invalid_texts.append(text)
                        if payload is not None:
                            return self._result(
                                payload,
                                frames_scanned,
                                invalid_texts,
                                started_at,
                                turn_count,
                            )
                        if self._time() >= deadline:
                            break

                        # 2. 只转一个短脉冲，并在 finally 中无条件停车。
                        self._turn_one_pulse(
                            direction=direction,
                            speed=turn_speed,
                            duration=turn_pulse_seconds,
                        )
                        turn_count += 1
                        if progress_fn is not None:
                            progress_fn(
                                f"scan frames={frames_scanned}, "
                                f"turn={turn_count}, direction={direction}"
                            )

                        # 3. 停稳后才继续识别，避免转动造成二维码拖影。
                        remaining = max(0.0, deadline - self._time())
                        self._sleep(min(settle_seconds, remaining))
                    if self._time() >= deadline:
                        break

            return self._result(
                None,
                frames_scanned,
                invalid_texts,
                started_at,
                turn_count,
            )
        finally:
            self.motor.brake()

    def _scan_stationary(self, *, deadline: float):
        """在一个停车位置连续读取图像并解析二维码。

        参数：
            deadline: 当前停车识别窗口的结束时刻。

        返回：
            ``(payload, frames_scanned, invalid_texts)``。
        """

        frames_scanned = 0
        invalid_texts = []
        while self._time() < deadline:
            frame = self.camera.read_frame()
            frames_scanned += 1
            for raw_text in self.recognizer.decode(frame):
                try:
                    return (
                        parse_qr_payload(raw_text),
                        frames_scanned,
                        invalid_texts,
                    )
                except QRCodeFormatError:
                    if raw_text not in invalid_texts:
                        invalid_texts.append(raw_text)
        return None, frames_scanned, invalid_texts

    def _turn_one_pulse(self, *, direction: str, speed: int, duration: float):
        """让底盘短时原地转向，并确保本次动作结束时停车。

        参数：
            direction: ``left`` 或 ``right``。
            speed: 左右轮 PWM 占空比。
            duration: 本次动作持续时间。
        """

        try:
            if direction == "left":
                self.motor.spin_left(speed, speed)
            else:
                self.motor.spin_right(speed, speed)
            self._sleep(duration)
        finally:
            self.motor.brake()

    def _result(
        self,
        payload,
        frames_scanned,
        invalid_texts,
        started_at,
        turn_count,
    ) -> QRScanResult:
        """汇总任务结果和运行统计信息。"""

        return QRScanResult(
            payload=payload,
            frames_scanned=frames_scanned,
            invalid_texts=tuple(invalid_texts),
            elapsed_seconds=max(0.0, self._time() - started_at),
            turn_count=turn_count,
        )

    @staticmethod
    def _validate_parameters(**values) -> None:
        """限制运动参数，防止误填导致持续高速转向。"""

        if values["timeout_seconds"] <= 0 or values["timeout_seconds"] > 120:
            raise ValueError("timeout_seconds 必须大于 0 且不超过 120")
        if values["turn_speed"] < 1 or values["turn_speed"] > 40:
            raise ValueError("turn_speed 必须在 1 到 40 之间")
        if (
            values["turn_pulse_seconds"] <= 0
            or values["turn_pulse_seconds"] > 0.5
        ):
            raise ValueError("turn_pulse_seconds 必须大于 0 且不超过 0.5")
        if values["settle_seconds"] < 0 or values["settle_seconds"] > 3:
            raise ValueError("settle_seconds 必须在 0 到 3 之间")
        if (
            values["scan_window_seconds"] <= 0
            or values["scan_window_seconds"] > 5
        ):
            raise ValueError("scan_window_seconds 必须大于 0 且不超过 5")
        if values["sweep_half_steps"] < 1 or values["sweep_half_steps"] > 20:
            raise ValueError("sweep_half_steps 必须在 1 到 20 之间")
