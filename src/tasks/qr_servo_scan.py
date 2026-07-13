"""使用摄像头双舵机云台自动搜索项目二维码。"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Optional, Sequence, Tuple

from src.algorithms.qr_detect import (
    QRCodeFormatError,
    QRCodePayload,
    parse_qr_payload,
)


@dataclass(frozen=True)
class QRServoScanResult:
    """双舵机二维码搜索结果。

    参数：
        payload: 成功识别的 TYPE:ID 内容；未找到时为 None。
        pan_angle: 成功时的左右舵机角度。
        tilt_angle: 成功时的上下舵机角度。
        positions_scanned: 已检查的云台位置数量。
        frames_scanned: 已交给二维码识别器的图像帧数。
        invalid_texts: 解码成功但格式无效的二维码文本。
        elapsed_seconds: 本次任务实际运行时间。
    """

    payload: Optional[QRCodePayload]
    pan_angle: Optional[float]
    tilt_angle: Optional[float]
    positions_scanned: int
    frames_scanned: int
    invalid_texts: Tuple[str, ...]
    elapsed_seconds: float


class QRCodeServoScanner:
    """组合摄像头、两个舵机和二维码算法进行视野搜索。

    参数：
        camera: 已打开并提供 read_frame() 的摄像头对象。
        pan_servo: 控制摄像头左右旋转的舵机对象。
        tilt_servo: 控制摄像头上下旋转的舵机对象。
        recognizer: 提供 decode(frame) 的二维码识别器。
        time_fn: 单调时钟函数，默认使用 time.monotonic。

    本任务不拥有硬件资源，不调用 close()；资源由入口层统一释放。
    """

    def __init__(
        self,
        camera,
        pan_servo,
        tilt_servo,
        recognizer,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        self.camera = camera
        self.pan_servo = pan_servo
        self.tilt_servo = tilt_servo
        self.recognizer = recognizer
        self._time = time_fn

    def scan(
        self,
        *,
        pan_angles: Sequence[float],
        tilt_angles: Sequence[float],
        frames_per_position: int = 10,
        discard_frames_after_move: int = 2,
        timeout_seconds: float = 30.0,
        progress_fn: Optional[Callable[[str], None]] = None,
    ) -> QRServoScanResult:
        """按上下和左右角度网格扫描，找到有效二维码后立即返回。

        参数：
            pan_angles: 左右舵机角度顺序，建议从 90 度中心开始。
            tilt_angles: 上下舵机角度顺序，建议从 90 度中心开始。
            frames_per_position: 每个稳定位置连续识别的帧数。
            discard_frames_after_move: 舵机移动后丢弃的摄像头缓冲帧数。
            timeout_seconds: 整个搜索任务的最长运行时间。
            progress_fn: 可选进度输出回调。

        返回：
            QRServoScanResult；成功时记录二维码内容和两个舵机角度。
        """

        normalized_pan = self._validate_angles("pan_angles", pan_angles)
        normalized_tilt = self._validate_angles("tilt_angles", tilt_angles)
        if frames_per_position < 1 or frames_per_position > 100:
            raise ValueError("frames_per_position 必须在 1 到 100 之间")
        if discard_frames_after_move < 0 or discard_frames_after_move > 30:
            raise ValueError("discard_frames_after_move 必须在 0 到 30 之间")
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("timeout_seconds 必须大于 0 且不超过 120")

        started_at = self._time()
        deadline = started_at + timeout_seconds
        positions_scanned = 0
        frames_scanned = 0
        invalid_texts = []

        # 1. 外层改变上下视角，内层在当前高度从中心向左右扫描。
        for tilt_angle in normalized_tilt:
            if self._time() >= deadline:
                break
            self.tilt_servo.move_to(tilt_angle)

            for pan_angle in normalized_pan:
                if self._time() >= deadline:
                    break
                self.pan_servo.move_to(pan_angle)
                positions_scanned += 1
                if progress_fn is not None:
                    progress_fn(
                        f"position={positions_scanned}, "
                        f"pan={pan_angle:.1f}, tilt={tilt_angle:.1f}"
                    )

                # 2. 丢弃舵机运动期间积压的帧，使用稳定后的最新画面。
                if discard_frames_after_move:
                    self.camera.read_frame(
                        warmup_frames=discard_frames_after_move - 1,
                        copy=False,
                    )

                # 3. 在同一稳定位置读取多帧，降低单帧模糊导致的漏识别。
                for _ in range(frames_per_position):
                    if self._time() >= deadline:
                        break
                    frame = self.camera.read_frame(copy=False)
                    frames_scanned += 1
                    for raw_text in self.recognizer.decode(frame):
                        try:
                            payload = parse_qr_payload(raw_text)
                        except QRCodeFormatError:
                            if raw_text not in invalid_texts:
                                invalid_texts.append(raw_text)
                            continue

                        # 成功后不复位云台，让摄像头保持朝向二维码的位置。
                        return self._build_result(
                            payload=payload,
                            pan_angle=pan_angle,
                            tilt_angle=tilt_angle,
                            positions_scanned=positions_scanned,
                            frames_scanned=frames_scanned,
                            invalid_texts=invalid_texts,
                            started_at=started_at,
                        )

        return self._build_result(
            payload=None,
            pan_angle=None,
            tilt_angle=None,
            positions_scanned=positions_scanned,
            frames_scanned=frames_scanned,
            invalid_texts=invalid_texts,
            started_at=started_at,
        )

    def _build_result(
        self,
        *,
        payload,
        pan_angle,
        tilt_angle,
        positions_scanned,
        frames_scanned,
        invalid_texts,
        started_at,
    ) -> QRServoScanResult:
        """将识别内容、角度和运行统计汇总为不可变结果。"""

        return QRServoScanResult(
            payload=payload,
            pan_angle=pan_angle,
            tilt_angle=tilt_angle,
            positions_scanned=positions_scanned,
            frames_scanned=frames_scanned,
            invalid_texts=tuple(invalid_texts),
            elapsed_seconds=max(0.0, self._time() - started_at),
        )

    @staticmethod
    def _validate_angles(name: str, angles: Sequence[float]) -> Tuple[float, ...]:
        """校验角度列表并转换为浮点元组。

        参数：
            name: 用于错误信息的参数名。
            angles: 待校验的舵机角度序列。
        """

        normalized = tuple(float(angle) for angle in angles)
        if not normalized:
            raise ValueError(f"{name} 至少需要一个角度")
        if any(angle < 0 or angle > 180 for angle in normalized):
            raise ValueError(f"{name} 中的角度必须在 0 到 180 之间")
        return normalized
