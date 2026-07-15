"""Classify a stopped obstacle from the backend's fixed camera stream."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Optional

from src.algorithms.qr_detect import QRCodeFormatError, parse_qr_payload
from src.hardware.camera import CameraCaptureError


OBSTACLE_TYPE_ORDINARY = "ordinary"
OBSTACLE_TYPE_TOLL = "toll"

CLASSIFICATION_SUCCESS = "success"
CLASSIFICATION_FAILED = "failed"

VISUAL_PHASE_SCANNING_TOLL_QR = "scanning_toll_qr"

ERROR_COLOR_TIMEOUT = "color_timeout"
ERROR_COLOR_CONFLICT = "color_conflict"
ERROR_COLOR_DETECTION = "color_detection_error"
ERROR_CAMERA_UNAVAILABLE = "camera_unavailable"
ERROR_QR_TIMEOUT = "qr_timeout"
ERROR_QR_INVALID_PAYLOAD = "qr_invalid_payload"
ERROR_QR_DETECTION = "qr_detection_error"
ERROR_CANCELED = "canceled"
VALID_RECOGNITION_ERRORS = (
    ERROR_COLOR_TIMEOUT,
    ERROR_COLOR_CONFLICT,
    ERROR_COLOR_DETECTION,
    ERROR_CAMERA_UNAVAILABLE,
    ERROR_QR_TIMEOUT,
    ERROR_QR_INVALID_PAYLOAD,
    ERROR_QR_DETECTION,
    ERROR_CANCELED,
)


@dataclass(frozen=True)
class ObstacleVisualResult:
    """Final visual facts used by navigation and obstacle persistence.

    Parameters:
    obstacle_type: ordinary or toll after applying the safe classification rule.
    detected_color: Stable red/blue fact, or None when color was not confirmed.
    classification_status: success or failed.
    station_id: Strict TOLL identifier when a toll QR code was decoded.
    recognition_error: Stable error code for a failed classification.
    record_frame: Exact original BGR frame selected for the final record.
    """

    obstacle_type: str
    detected_color: Optional[str]
    classification_status: str
    station_id: Optional[str]
    recognition_error: Optional[str]
    record_frame: Optional[Any]


class ObstacleVisualClassificationTask:
    """Run red/blue confirmation and conditional toll QR recognition.

    Parameters:
    color_detector: ColorDetector configured for red and blue only.
    qr_recognizer: QRCodeRecognizer using the existing OpenCV decoder.
    camera: BackendCamera owning the process's only task-scoped camera handle.
    color_confirm_frames: Consecutive unambiguous frames required for a color.
    color_timeout_seconds/qr_timeout_seconds: Independent phase time budgets.
    monotonic_fn: Monotonic clock used to enforce both deadlines.
    """

    def __init__(
        self,
        color_detector,
        qr_recognizer,
        camera,
        *,
        color_confirm_frames: int = 3,
        color_timeout_seconds: float = 15.0,
        qr_timeout_seconds: float = 30.0,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ):
        if color_confirm_frames <= 0:
            raise ValueError("color_confirm_frames must be greater than 0")
        if color_timeout_seconds <= 0 or qr_timeout_seconds <= 0:
            raise ValueError("visual timeouts must be greater than 0")
        self.color_detector = color_detector
        self.qr_recognizer = qr_recognizer
        self.camera = camera
        self.color_confirm_frames = color_confirm_frames
        self.color_timeout_seconds = color_timeout_seconds
        self.qr_timeout_seconds = qr_timeout_seconds
        self._monotonic = monotonic_fn

    def classify(
        self,
        cancel_requested_fn: Optional[Callable[[], bool]] = None,
        phase_changed_fn: Optional[Callable[[str], None]] = None,
    ) -> ObstacleVisualResult:
        """Return one final visual result without operating motors or storage.

        Steps:
        Confirm one unambiguous dominant color across consecutive frames. Red ends
        immediately as an ordinary obstacle; blue starts a fresh QR time budget and
        only a strict TOLL payload can produce a toll result.
        """

        deadline = self._monotonic() + self.color_timeout_seconds
        consecutive_color = None
        consecutive_count = 0
        conflict_seen = False
        best_frame = None
        best_area = -1.0
        last_frame = None

        try:
            while self._monotonic() < deadline:
                if self._is_canceled(cancel_requested_fn):
                    return self._failed_result(
                        None,
                        ERROR_CANCELED,
                        best_frame if best_frame is not None else last_frame,
                    )
                try:
                    frame = self.camera.read_frame()
                except CameraCaptureError:
                    # 设备短暂掉线时，BackendCamera 已释放旧句柄；下一轮重开。
                    time.sleep(0.1)
                    continue
                last_frame = frame
                try:
                    detection = self.color_detector.detect(frame)
                except Exception:
                    return self._failed_result(None, ERROR_COLOR_DETECTION, frame)

                colors = {region.color for region in detection.regions}
                if "red" in colors and "blue" in colors:
                    conflict_seen = True
                    consecutive_color = None
                    consecutive_count = 0
                    best_frame = frame
                    continue

                color = detection.dominant_color
                if color not in ("red", "blue"):
                    consecutive_color = None
                    consecutive_count = 0
                    continue

                area = detection.regions[0].area
                if area > best_area:
                    best_area = area
                    best_frame = frame
                if color == consecutive_color:
                    consecutive_count += 1
                else:
                    consecutive_color = color
                    consecutive_count = 1
                if consecutive_count < self.color_confirm_frames:
                    continue

                if color == "red":
                    return ObstacleVisualResult(
                        OBSTACLE_TYPE_ORDINARY,
                        "red",
                        CLASSIFICATION_SUCCESS,
                        None,
                        None,
                        frame,
                    )
                if phase_changed_fn is not None:
                    phase_changed_fn(VISUAL_PHASE_SCANNING_TOLL_QR)
                return self._scan_toll_qr(
                    color_frame=frame,
                    cancel_requested_fn=cancel_requested_fn,
                )

            if self._is_canceled(cancel_requested_fn):
                return self._failed_result(
                    None,
                    ERROR_CANCELED,
                    best_frame if best_frame is not None else last_frame,
                )
            if last_frame is None:
                error = ERROR_CAMERA_UNAVAILABLE
            else:
                error = (
                    ERROR_COLOR_CONFLICT if conflict_seen else ERROR_COLOR_TIMEOUT
                )
            return self._failed_result(
                None,
                error,
                best_frame if best_frame is not None else last_frame,
            )
        finally:
            self.camera.close()

    def _scan_toll_qr(
        self,
        *,
        color_frame,
        cancel_requested_fn,
    ) -> ObstacleVisualResult:
        """Scan subsequent frames for one strict TOLL payload after blue confirmation."""

        deadline = self._monotonic() + self.qr_timeout_seconds
        invalid_payload_seen = False
        qr_frame_seen = False
        diagnostic_frame = color_frame
        while self._monotonic() < deadline:
            if self._is_canceled(cancel_requested_fn):
                return self._failed_result("blue", ERROR_CANCELED, diagnostic_frame)
            try:
                frame = self.camera.read_frame()
            except CameraCaptureError:
                time.sleep(0.1)
                continue
            qr_frame_seen = True
            diagnostic_frame = frame
            try:
                diagnostics = self.qr_recognizer.decode_with_diagnostics(frame)
            except Exception:
                return self._failed_result("blue", ERROR_QR_DETECTION, frame)

            for raw_text in diagnostics.texts:
                try:
                    payload = parse_qr_payload(raw_text)
                except QRCodeFormatError:
                    invalid_payload_seen = True
                    continue
                if payload.qr_type != "TOLL":
                    invalid_payload_seen = True
                    continue
                return ObstacleVisualResult(
                    OBSTACLE_TYPE_TOLL,
                    "blue",
                    CLASSIFICATION_SUCCESS,
                    payload.identifier,
                    None,
                    frame,
                )

        if self._is_canceled(cancel_requested_fn):
            return self._failed_result("blue", ERROR_CANCELED, diagnostic_frame)
        if invalid_payload_seen:
            error = ERROR_QR_INVALID_PAYLOAD
        elif qr_frame_seen:
            error = ERROR_QR_TIMEOUT
        else:
            error = ERROR_CAMERA_UNAVAILABLE
        return self._failed_result("blue", error, diagnostic_frame)

    @staticmethod
    def _failed_result(detected_color, error, frame):
        """Build the single safe ordinary-obstacle result for every visual failure."""

        return ObstacleVisualResult(
            OBSTACLE_TYPE_ORDINARY,
            detected_color,
            CLASSIFICATION_FAILED,
            None,
            error,
            frame,
        )

    @staticmethod
    def _is_canceled(cancel_requested_fn):
        return cancel_requested_fn is not None and bool(cancel_requested_fn())
