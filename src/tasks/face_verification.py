"""Verify one expected passenger from the backend's fixed camera stream."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Optional


FACE_MATCHED = "matched"
FACE_TIMEOUT = "timeout"
FACE_CANCELED = "canceled"


@dataclass(frozen=True)
class FaceVerificationResult:
    """一次指定乘客核验的最终结果。

    参数说明：
    outcome: matched、timeout 或 canceled。
    detected_passenger_id: 最有诊断价值的人脸标签，未知人脸为 None。
    distance: 对应人脸匹配距离，没有检测到人脸时为 None。
    frame: 成功确认帧或超时诊断帧；取消时为 None。
    """

    outcome: str
    detected_passenger_id: Optional[str]
    distance: Optional[float]
    frame: Optional[Any]


class FaceVerificationTask:
    """从固定摄像头连续帧中核验本次行程指定乘客。

    参数说明：
    recognizer: 已加载人脸数据集的 LocalFaceRecognizer。
    camera: 后端唯一 BackendCamera 实例。
    confirm_frames: 指定乘客需要连续匹配的帧数。
    timeout_seconds: 单次核验最长时间。
    monotonic_fn: 单调时钟，便于稳定控制超时边界。
    """

    def __init__(
        self,
        recognizer,
        camera,
        *,
        confirm_frames: int = 3,
        timeout_seconds: float = 20.0,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ):
        if confirm_frames <= 0:
            raise ValueError("confirm_frames must be greater than 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        self.recognizer = recognizer
        self.camera = camera
        self.confirm_frames = confirm_frames
        self.timeout_seconds = timeout_seconds
        self._monotonic = monotonic_fn

    @property
    def passenger_ids(self):
        """返回启动时已经成功加载的乘客标签。"""

        return self.recognizer.labels

    def verify(
        self,
        expected_passenger_id: str,
        cancel_requested_fn: Optional[Callable[[], bool]] = None,
    ) -> FaceVerificationResult:
        """连续核验指定乘客，成功、超时或取消时返回一项最终结果。

        分步逻辑：
        1. 每帧先检查取消，再读取唯一摄像头会话。
        2. 只累计指定乘客的连续匹配帧，其他结果立即清零。
        3. 保存最接近阈值的人脸帧供超时诊断；无脸时保留最后一帧。
        """

        if expected_passenger_id not in self.passenger_ids:
            raise ValueError("expected_passenger_id is not loaded")

        deadline = self._monotonic() + self.timeout_seconds
        consecutive = 0
        last_frame = None
        best_frame = None
        best_label = None
        best_distance = float("inf")

        while self._monotonic() < deadline:
            if cancel_requested_fn is not None and cancel_requested_fn():
                return FaceVerificationResult(FACE_CANCELED, None, None, None)

            frame = self.camera.read_frame()
            last_frame = frame
            matches = self.recognizer.recognize(frame)
            if matches:
                closest = min(matches, key=lambda item: item.distance)
                if closest.distance < best_distance:
                    best_frame = frame
                    best_label = closest.label
                    best_distance = closest.distance

            expected_matches = [
                match for match in matches if match.label == expected_passenger_id
            ]
            if not expected_matches:
                consecutive = 0
                continue

            expected_match = min(expected_matches, key=lambda item: item.distance)
            consecutive += 1
            if consecutive >= self.confirm_frames:
                return FaceVerificationResult(
                    FACE_MATCHED,
                    expected_passenger_id,
                    float(expected_match.distance),
                    frame,
                )

        if cancel_requested_fn is not None and cancel_requested_fn():
            return FaceVerificationResult(FACE_CANCELED, None, None, None)
        return FaceVerificationResult(
            FACE_TIMEOUT,
            best_label,
            float(best_distance) if best_distance < float("inf") else None,
            best_frame if best_frame is not None else last_frame,
        )
