"""使用摄像头双舵机云台自动搜索项目二维码。"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, Optional, Sequence, Tuple

from src.algorithms.qr_detect import (
    QRCodeFormatError,
    QRCodePayload,
    parse_qr_payload,
)
from src.tasks.camera_servo_scan import CameraServoScanner


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
        last_frame: 扫码期间最后取得的画面，供入口层在失败时保存诊断快照。
    """

    payload: Optional[QRCodePayload]
    pan_angle: Optional[float]
    tilt_angle: Optional[float]
    positions_scanned: int
    frames_scanned: int
    invalid_texts: Tuple[str, ...]
    elapsed_seconds: float
    last_frame: Optional[object] = field(repr=False, compare=False)


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

        invalid_texts = []

        def decode_frame(scan_frame):
            """Return the first valid project payload from one shared scan frame."""

            for raw_text in self.recognizer.decode(scan_frame.frame):
                try:
                    return parse_qr_payload(raw_text)
                except QRCodeFormatError:
                    if raw_text not in invalid_texts:
                        invalid_texts.append(raw_text)
            return None

        shared_result = CameraServoScanner(
            self.camera,
            self.pan_servo,
            self.tilt_servo,
            time_fn=self._time,
        ).scan(
            decode_frame,
            pan_angles=pan_angles,
            tilt_angles=tilt_angles,
            frames_per_position=frames_per_position,
            discard_frames_after_move=discard_frames_after_move,
            timeout_seconds=timeout_seconds,
            progress_fn=progress_fn,
        )
        payload = shared_result.value
        return QRServoScanResult(
            payload=payload,
            pan_angle=shared_result.pan_angle if payload is not None else None,
            tilt_angle=shared_result.tilt_angle if payload is not None else None,
            positions_scanned=shared_result.positions_scanned,
            frames_scanned=shared_result.frames_scanned,
            invalid_texts=tuple(invalid_texts),
            elapsed_seconds=shared_result.elapsed_seconds,
            last_frame=shared_result.last_frame,
        )
