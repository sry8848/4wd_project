"""Panorama capture workflow for the Yahboom 4WD car.

The workflow is intentionally split into small steps: move the camera pan
servo, capture one frame, keep every source frame, and optionally stitch the
frames into a final panorama image.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Optional, Sequence, Tuple, Union

from src import config
from src.hardware.camera import (
    CameraBackend,
    OpenCVCameraSession,
    OpenCVCameraSettings,
    capture_photo,
)
from src.hardware.servo import ServoController


DEFAULT_PANORAMA_DIR = Path("captures") / "panoramas"
PathLike = Union[str, Path]


class PanoramaError(RuntimeError):
    """Raised when panorama capture or stitching fails."""


@dataclass(frozen=True)
class PanoramaResult:
    """Metadata for one panorama capture run."""

    session_dir: Path
    frame_paths: Tuple[Path, ...]
    panorama_path: Optional[Path]
    angles: Tuple[float, ...]


def build_angle_sequence(
    start_angle: float,
    end_angle: float,
    frame_count: int,
) -> Tuple[float, ...]:
    """Build evenly spaced servo angles for panorama capture.

    Args:
        start_angle: First pan angle, from 0 to 180 degrees.
        end_angle: Last pan angle, from 0 to 180 degrees.
        frame_count: Number of photos to capture.

    Returns:
        Tuple of angles in capture order.
    """

    if frame_count < 1:
        raise ValueError("frame_count must be greater than or equal to 1")
    _validate_angle("start_angle", start_angle)
    _validate_angle("end_angle", end_angle)

    if frame_count == 1:
        return (float(start_angle),)

    step = (float(end_angle) - float(start_angle)) / (frame_count - 1)
    return tuple(round(float(start_angle) + index * step, 3) for index in range(frame_count))


def build_session_dir(
    output_dir: PathLike = DEFAULT_PANORAMA_DIR,
    *,
    session_name: Optional[str] = None,
) -> Path:
    """Build a timestamped directory for one panorama run.

    Args:
        output_dir: Parent directory for panorama sessions.
        session_name: Optional exact session folder name.

    Returns:
        A path such as ``captures/panoramas/panorama_20260709_120000``.
    """

    clean_name = session_name or datetime.now().strftime("panorama_%Y%m%d_%H%M%S")
    return Path(output_dir) / clean_name


def capture_panorama(
    *,
    output_dir: PathLike = DEFAULT_PANORAMA_DIR,
    session_name: Optional[str] = None,
    backend: CameraBackend = "auto",
    device_index: int = 0,
    width: Optional[int] = 1280,
    height: Optional[int] = 960,
    warmup_frames: int = 5,
    warmup_seconds: float = 0.5,
    start_angle: float = config.PANORAMA_START_ANGLE,
    end_angle: float = config.PANORAMA_END_ANGLE,
    frame_count: int = config.PANORAMA_FRAME_COUNT,
    pan_servo_pin: Optional[int] = config.CAMERA_PAN_SERVO_PIN,
    tilt_servo_pin: Optional[int] = config.CAMERA_TILT_SERVO_PIN,
    tilt_angle: Optional[float] = config.PANORAMA_TILT_ANGLE,
    use_servo: bool = True,
    servo_settle_seconds: float = 0.5,
    capture_delay_seconds: float = 0.4,
    camera_settings: Optional[OpenCVCameraSettings] = None,
    burst_count: int = 1,
    stitch: bool = True,
    stitch_confidence: float = 0.01,
) -> PanoramaResult:
    """Capture a panorama source sequence and optionally stitch it.

    Args:
        output_dir: Parent directory for the panorama session folder.
        session_name: Optional exact session folder name.
        backend: Camera backend. ``opencv`` keeps one camera session open.
        device_index: OpenCV camera index.
        width: Requested camera frame width.
        height: Requested camera frame height.
        warmup_frames: Camera frames to discard before saving a photo.
        warmup_seconds: Delay after opening the camera.
        start_angle: First horizontal pan angle.
        end_angle: Last horizontal pan angle.
        frame_count: Number of photos to take.
        pan_servo_pin: BCM pin for the horizontal camera pan servo.
        tilt_servo_pin: Optional BCM pin for a vertical camera tilt servo.
        tilt_angle: Optional fixed tilt angle before the pan sweep starts.
        use_servo: Whether to move servos between photos.
        servo_settle_seconds: Delay after each servo angle command.
        capture_delay_seconds: Extra delay before reading each frame.
        camera_settings: Optional OpenCV camera controls.
        burst_count: Number of candidate frames to score and choose from.
        stitch: Whether to create ``panorama.jpg`` after capture.
        stitch_confidence: OpenCV Stitcher confidence threshold.

    Returns:
        PanoramaResult with source frame paths and optional panorama path.
    """

    if backend not in ("auto", "opencv", "libcamera", "raspistill"):
        raise ValueError(f"unsupported backend: {backend}")
    if warmup_frames < 0:
        raise ValueError("warmup_frames must be greater than or equal to 0")
    if warmup_seconds < 0:
        raise ValueError("warmup_seconds must be greater than or equal to 0")
    if servo_settle_seconds < 0:
        raise ValueError("servo_settle_seconds must be greater than or equal to 0")
    if capture_delay_seconds < 0:
        raise ValueError("capture_delay_seconds must be greater than or equal to 0")
    if burst_count < 1:
        raise ValueError("burst_count must be greater than or equal to 1")
    if tilt_angle is not None:
        _validate_angle("tilt_angle", tilt_angle)

    angles = build_angle_sequence(start_angle, end_angle, frame_count)
    session_dir = build_session_dir(output_dir, session_name=session_name)
    frames_dir = session_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    pan_servo = None
    tilt_servo = None
    try:
        if use_servo:
            if pan_servo_pin is None:
                raise PanoramaError("pan_servo_pin is required unless use_servo is False")
            pan_servo = ServoController(
                pan_servo_pin,
                settle_seconds=servo_settle_seconds,
            )
            if tilt_servo_pin is not None and tilt_angle is not None:
                tilt_servo = ServoController(
                    tilt_servo_pin,
                    settle_seconds=servo_settle_seconds,
                )
                tilt_servo.move_to(tilt_angle)

        frame_paths = _capture_frames(
            frames_dir=frames_dir,
            angles=angles,
            pan_servo=pan_servo,
            backend=backend,
            device_index=device_index,
            width=width,
            height=height,
            warmup_frames=warmup_frames,
            warmup_seconds=warmup_seconds,
            capture_delay_seconds=capture_delay_seconds,
            camera_settings=camera_settings,
            burst_count=burst_count,
        )
    finally:
        # 实机异常时也要停止 PWM 并释放本任务占用的舵机 GPIO。
        if tilt_servo is not None:
            tilt_servo.close()
        if pan_servo is not None:
            pan_servo.close()

    panorama_path = None
    if stitch:
        panorama_path = stitch_images(
            frame_paths,
            session_dir / "panorama.jpg",
            confidence_threshold=stitch_confidence,
        )

    return PanoramaResult(
        session_dir=session_dir,
        frame_paths=tuple(frame_paths),
        panorama_path=panorama_path,
        angles=angles,
    )


def stitch_images(
    image_paths: Sequence[PathLike],
    output_path: PathLike,
    *,
    confidence_threshold: float = 0.01,
) -> Path:
    """Stitch captured frames into one panorama image.

    Args:
        image_paths: Source image paths in left-to-right capture order.
        output_path: Final panorama image path.
        confidence_threshold: OpenCV Stitcher confidence threshold.

    Returns:
        Path to the written panorama image.
    """

    if len(image_paths) < 2:
        raise PanoramaError("at least two images are required for stitching")

    try:
        import cv2
    except ImportError as exc:
        raise PanoramaError("OpenCV is required for panorama stitching") from exc

    images = []
    for image_path in image_paths:
        path = Path(image_path)
        image = cv2.imread(str(path))
        if image is None:
            raise PanoramaError(f"cannot read source image: {path}")
        images.append(image)

    stitcher = _create_stitcher(cv2)
    if hasattr(stitcher, "setPanoConfidenceThresh"):
        stitcher.setPanoConfidenceThresh(confidence_threshold)

    status, panorama = stitcher.stitch(images)
    ok_status = getattr(cv2, "Stitcher_OK", 0)
    if status != ok_status or panorama is None:
        raise PanoramaError(_format_stitch_error(status))

    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target_path), panorama):
        raise PanoramaError(f"failed to write panorama image: {target_path}")
    return target_path


def _capture_frames(
    *,
    frames_dir: Path,
    angles: Sequence[float],
    pan_servo: Optional[ServoController],
    backend: CameraBackend,
    device_index: int,
    width: Optional[int],
    height: Optional[int],
    warmup_frames: int,
    warmup_seconds: float,
    capture_delay_seconds: float,
    camera_settings: Optional[OpenCVCameraSettings],
    burst_count: int,
) -> Tuple[Path, ...]:
    """Capture all source frames for one panorama run."""

    if backend == "opencv":
        return _capture_frames_with_opencv_session(
            frames_dir=frames_dir,
            angles=angles,
            pan_servo=pan_servo,
            device_index=device_index,
            width=width,
            height=height,
            warmup_frames=warmup_frames,
            warmup_seconds=warmup_seconds,
            capture_delay_seconds=capture_delay_seconds,
            camera_settings=camera_settings,
            burst_count=burst_count,
        )

    frame_paths = []
    for index, angle in enumerate(angles):
        if pan_servo is not None:
            pan_servo.move_to(angle)
        if capture_delay_seconds > 0:
            time.sleep(capture_delay_seconds)

        frame_path = _frame_path(frames_dir, index, angle)
        capture_photo(
            output_path=frame_path,
            backend=backend,
            device_index=device_index,
            width=width,
            height=height,
            warmup_frames=warmup_frames,
            warmup_seconds=warmup_seconds,
            settings=camera_settings,
            burst_count=burst_count,
        )
        frame_paths.append(frame_path)
    return tuple(frame_paths)


def _capture_frames_with_opencv_session(
    *,
    frames_dir: Path,
    angles: Sequence[float],
    pan_servo: Optional[ServoController],
    device_index: int,
    width: Optional[int],
    height: Optional[int],
    warmup_frames: int,
    warmup_seconds: float,
    capture_delay_seconds: float,
    camera_settings: Optional[OpenCVCameraSettings],
    burst_count: int,
) -> Tuple[Path, ...]:
    """Capture all source frames while keeping one OpenCV camera open."""

    frame_paths = []
    with OpenCVCameraSession(
        device_index=device_index,
        width=width,
        height=height,
        warmup_frames=warmup_frames,
        warmup_seconds=warmup_seconds,
        settings=camera_settings,
    ) as camera:
        for index, angle in enumerate(angles):
            if pan_servo is not None:
                pan_servo.move_to(angle)
            frame_path = _frame_path(frames_dir, index, angle)
            camera.capture(
                frame_path,
                warmup_frames=0,
                delay_seconds=capture_delay_seconds,
                burst_count=burst_count,
            )
            frame_paths.append(frame_path)
    return tuple(frame_paths)


def _create_stitcher(cv2):
    """Create an OpenCV Stitcher across common OpenCV versions."""

    if hasattr(cv2, "Stitcher_create"):
        if hasattr(cv2, "Stitcher_PANORAMA"):
            return cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
        return cv2.Stitcher_create()
    if hasattr(cv2, "createStitcher"):
        return cv2.createStitcher(False)
    raise PanoramaError("current OpenCV build does not provide Stitcher")


def _frame_path(frames_dir: Path, index: int, angle: float) -> Path:
    return frames_dir / f"frame_{index:02d}_angle_{_format_angle(angle)}.jpg"


def _format_angle(angle: float) -> str:
    if float(angle).is_integer():
        return f"{int(angle):03d}"
    return f"{angle:07.3f}".replace(".", "p").replace("-", "m")


def _validate_angle(name: str, angle: float) -> None:
    value = float(angle)
    if value < 0 or value > 180:
        raise ValueError(f"{name} must be between 0 and 180 degrees")


def _format_stitch_error(status: int) -> str:
    hints = {
        1: "need more matching features or more overlap between photos",
        2: "homography estimation failed; try slower movement or more overlap",
        3: "camera parameter adjustment failed; try fewer blur/exposure changes",
    }
    hint = hints.get(status, "unknown OpenCV Stitcher error")
    return f"panorama stitching failed with status {status}: {hint}"
