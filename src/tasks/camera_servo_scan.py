"""Shared two-axis camera-servo scan orchestration for vision features."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class CameraServoFrame:
    """One camera frame captured at a confirmed pan/tilt scan position.

    Args:
        frame: OpenCV image returned by the injected camera.
        pan_angle: Current left/right servo angle.
        tilt_angle: Current up/down servo angle.
        position_index: One-based index of the current scan position.
        frame_index: One-based frame index at this position.
    """

    frame: object = field(repr=False, compare=False)
    pan_angle: float
    tilt_angle: float
    position_index: int
    frame_index: int


@dataclass(frozen=True)
class CameraServoScanResult:
    """Result and statistics returned by the shared camera-servo scan."""

    value: Optional[object] = field(repr=False, compare=False)
    pan_angle: Optional[float]
    tilt_angle: Optional[float]
    positions_scanned: int
    frames_scanned: int
    elapsed_seconds: float
    timed_out: bool
    last_frame: Optional[object] = field(repr=False, compare=False)


class CameraServoScanner:
    """Move a two-axis camera through a shared grid and process each frame.

    Args:
        camera: Open camera object providing read_frame().
        pan_servo: Left/right servo object providing move_to().
        tilt_servo: Up/down servo object providing move_to().
        time_fn: Monotonic clock used for the whole-scan deadline.

    This task does not own or close hardware. The entry tool must create all
    objects in one outer context and release them after scan completion.
    """

    def __init__(
        self,
        camera,
        pan_servo,
        tilt_servo,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        self.camera = camera
        self.pan_servo = pan_servo
        self.tilt_servo = tilt_servo
        self._time = time_fn

    def scan(
        self,
        frame_handler: Callable[[CameraServoFrame], Optional[object]],
        *,
        pan_angles: Sequence[float],
        tilt_angles: Sequence[float],
        frames_per_position: int = 10,
        discard_frames_after_move: int = 2,
        timeout_seconds: float = 30.0,
        progress_fn: Optional[Callable[[str], None]] = None,
    ) -> CameraServoScanResult:
        """Scan the configured angle grid until the handler returns a value.

        Args:
            frame_handler: Feature callback. Return None to continue or any
                result object to stop at the current camera direction.
            pan_angles: Left/right angles, normally center then alternating sides.
            tilt_angles: Up/down angles, normally center then alternating heights.
            frames_per_position: Frames supplied to the feature at each position.
            discard_frames_after_move: Buffered frames discarded after movement.
            timeout_seconds: Maximum duration for movement and frame processing.
            progress_fn: Optional terminal progress callback.

        Steps:
        1. Move tilt on the outer loop and pan on the inner loop.
        2. Discard movement-period frames, then call the feature for fresh frames.
        3. Stop on the first non-None feature result or the whole-scan deadline.
        """

        normalized_pan = self.validate_angles("pan_angles", pan_angles)
        normalized_tilt = self.validate_angles("tilt_angles", tilt_angles)
        if frames_per_position < 1 or frames_per_position > 100:
            raise ValueError("frames_per_position must be between 1 and 100")
        if discard_frames_after_move < 0 or discard_frames_after_move > 30:
            raise ValueError("discard_frames_after_move must be between 0 and 30")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be greater than 0 and at most 300")

        started_at = self._time()
        deadline = started_at + timeout_seconds
        positions_scanned = 0
        frames_scanned = 0
        last_frame = None
        last_pan = None
        last_tilt = None

        for tilt_angle in normalized_tilt:
            if self._time() >= deadline:
                break
            self.tilt_servo.move_to(tilt_angle)

            for pan_angle in normalized_pan:
                if self._time() >= deadline:
                    break
                self.pan_servo.move_to(pan_angle)
                positions_scanned += 1
                last_pan = pan_angle
                last_tilt = tilt_angle
                if progress_fn is not None:
                    progress_fn(
                        f"position={positions_scanned}, "
                        f"pan={pan_angle:.1f}, tilt={tilt_angle:.1f}"
                    )

                if discard_frames_after_move:
                    last_frame = self.camera.read_frame(
                        warmup_frames=discard_frames_after_move - 1,
                        copy=False,
                    )

                for frame_index in range(1, frames_per_position + 1):
                    if self._time() >= deadline:
                        break
                    frame = self.camera.read_frame(copy=False)
                    last_frame = frame
                    frames_scanned += 1
                    value = frame_handler(
                        CameraServoFrame(
                            frame=frame,
                            pan_angle=pan_angle,
                            tilt_angle=tilt_angle,
                            position_index=positions_scanned,
                            frame_index=frame_index,
                        )
                    )
                    if value is not None:
                        return self._build_result(
                            value=value,
                            pan_angle=pan_angle,
                            tilt_angle=tilt_angle,
                            positions_scanned=positions_scanned,
                            frames_scanned=frames_scanned,
                            started_at=started_at,
                            deadline=deadline,
                            last_frame=last_frame,
                        )

        return self._build_result(
            value=None,
            pan_angle=last_pan,
            tilt_angle=last_tilt,
            positions_scanned=positions_scanned,
            frames_scanned=frames_scanned,
            started_at=started_at,
            deadline=deadline,
            last_frame=last_frame,
        )

    def _build_result(
        self,
        *,
        value,
        pan_angle,
        tilt_angle,
        positions_scanned,
        frames_scanned,
        started_at,
        deadline,
        last_frame,
    ) -> CameraServoScanResult:
        """Build one immutable result using the shared monotonic clock."""

        finished_at = self._time()
        return CameraServoScanResult(
            value=value,
            pan_angle=pan_angle,
            tilt_angle=tilt_angle,
            positions_scanned=positions_scanned,
            frames_scanned=frames_scanned,
            elapsed_seconds=max(0.0, finished_at - started_at),
            timed_out=finished_at >= deadline,
            last_frame=last_frame,
        )

    @staticmethod
    def validate_angles(name: str, angles: Sequence[float]) -> Tuple[float, ...]:
        """Validate one non-empty camera-servo angle sequence."""

        normalized = tuple(float(angle) for angle in angles)
        if not normalized:
            raise ValueError(f"{name} must contain at least one angle")
        if any(angle < 0 or angle > 180 for angle in normalized):
            raise ValueError(f"{name} angles must be between 0 and 180")
        return normalized
