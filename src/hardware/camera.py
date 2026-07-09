"""Camera capture helpers for Raspberry Pi car experiments.

The preferred backend is OpenCV because it works well with USB cameras. CSI
cameras on Raspberry Pi OS may use either ``libcamera-still`` on newer images
or ``raspistill`` on older Yahboom/Raspberry Pi images.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import time
from typing import Optional, Union


DEFAULT_CAPTURE_DIR = Path("captures")
DEFAULT_PHOTO_PREFIX = "photo"
DEFAULT_PHOTO_EXTENSION = ".jpg"
CameraBackend = str
DEFAULT_BACKEND: CameraBackend = "auto"


class CameraCaptureError(RuntimeError):
    """Raised when the camera cannot capture or save a frame."""


@dataclass(frozen=True)
class CaptureResult:
    """Metadata for one saved camera frame."""

    path: Path
    width: int
    height: int
    device_index: Optional[int]
    backend: str


PathLike = Union[str, Path]


def build_photo_path(
    output_dir: PathLike = DEFAULT_CAPTURE_DIR,
    prefix: str = DEFAULT_PHOTO_PREFIX,
    extension: str = DEFAULT_PHOTO_EXTENSION,
) -> Path:
    """Build a timestamped output path for one captured photo."""

    clean_extension = extension if extension.startswith(".") else "." + extension
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(output_dir) / f"{prefix}_{timestamp}{clean_extension}"


def capture_photo(
    output_path: Optional[PathLike] = None,
    *,
    output_dir: PathLike = DEFAULT_CAPTURE_DIR,
    prefix: str = DEFAULT_PHOTO_PREFIX,
    extension: str = DEFAULT_PHOTO_EXTENSION,
    backend: CameraBackend = DEFAULT_BACKEND,
    device_index: int = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    warmup_frames: int = 5,
    warmup_seconds: float = 0.5,
) -> CaptureResult:
    """Capture one photo from an OpenCV camera and save it to disk.

    Args:
        output_path: Exact file path to save. If omitted, a timestamped path is
            created under ``output_dir``.
        output_dir: Directory used when ``output_path`` is omitted.
        prefix: Filename prefix used when ``output_path`` is omitted.
        extension: File extension used when ``output_path`` is omitted.
        backend: ``opencv`` for USB cameras, ``libcamera`` or ``raspistill``
            for CSI cameras, or ``auto`` to try known backends in order.
        device_index: OpenCV camera index, usually 0 or 1 on Raspberry Pi.
        width: Optional requested frame width.
        height: Optional requested frame height.
        warmup_frames: Number of frames to discard before saving the final one.
        warmup_seconds: Delay after opening the camera, allowing exposure to
            stabilize.

    Returns:
        CaptureResult containing the saved path and frame dimensions.
    """

    if warmup_frames < 0:
        raise ValueError("warmup_frames must be greater than or equal to 0")
    if warmup_seconds < 0:
        raise ValueError("warmup_seconds must be greater than or equal to 0")

    target_path = (
        Path(output_path)
        if output_path is not None
        else build_photo_path(output_dir, prefix, extension)
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    errors = []

    if backend in ("auto", "opencv"):
        try:
            return _capture_with_opencv(
                target_path=target_path,
                device_index=device_index,
                width=width,
                height=height,
                warmup_frames=warmup_frames,
                warmup_seconds=warmup_seconds,
            )
        except CameraCaptureError as exc:
            if backend == "opencv":
                raise
            errors.append(f"opencv: {exc}")

    if backend in ("auto", "libcamera"):
        try:
            return _capture_with_libcamera(
                target_path=target_path,
                width=width,
                height=height,
                warmup_seconds=warmup_seconds,
            )
        except CameraCaptureError as exc:
            if backend == "libcamera":
                raise
            errors.append(f"libcamera: {exc}")

    if backend in ("auto", "raspistill"):
        try:
            return _capture_with_raspistill(
                target_path=target_path,
                width=width,
                height=height,
                warmup_seconds=warmup_seconds,
            )
        except CameraCaptureError as exc:
            if backend == "raspistill":
                raise
            errors.append(f"raspistill: {exc}")

    detail = "; ".join(errors) if errors else f"unsupported backend: {backend}"
    raise CameraCaptureError(
        f"Camera capture failed ({detail}). Try --device 1, --backend "
        "raspistill, --backend libcamera, or stop services such as "
        "mjpg-streamer that may own the camera."
    )


def _capture_with_opencv(
    *,
    target_path: Path,
    device_index: int,
    width: Optional[int],
    height: Optional[int],
    warmup_frames: int,
    warmup_seconds: float,
) -> CaptureResult:
    try:
        import cv2
    except ImportError as exc:
        raise CameraCaptureError(
            "OpenCV is not installed. Install python3-opencv, or use "
            "--backend libcamera if this is a CSI camera."
        ) from exc

    camera = cv2.VideoCapture(device_index)
    try:
        if not camera.isOpened():
            raise CameraCaptureError(
                f"Cannot open camera device {device_index}. Check the camera "
                "index, connection, and whether a video service is using it."
            )

        if width is not None:
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height is not None:
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        if warmup_seconds > 0:
            time.sleep(warmup_seconds)

        frame = None
        reads = max(1, warmup_frames + 1)
        for _ in range(reads):
            ok, current_frame = camera.read()
            if ok and current_frame is not None:
                frame = current_frame
            else:
                time.sleep(0.05)

        if frame is None:
            raise CameraCaptureError(
                f"Camera device {device_index} opened, but no frame was read."
            )

        saved = cv2.imwrite(str(target_path), frame)
        if not saved:
            raise CameraCaptureError(f"Failed to write photo to {target_path}")

        frame_height, frame_width = frame.shape[:2]
        return CaptureResult(
            path=target_path,
            width=int(frame_width),
            height=int(frame_height),
            device_index=device_index,
            backend="opencv",
        )
    finally:
        camera.release()


def _capture_with_libcamera(
    *,
    target_path: Path,
    width: Optional[int],
    height: Optional[int],
    warmup_seconds: float,
) -> CaptureResult:
    executable = shutil.which("libcamera-still")
    if executable is None:
        raise CameraCaptureError("libcamera-still command was not found")

    timeout_ms = max(1, int(warmup_seconds * 1000))
    command = [
        executable,
        "--nopreview",
        "--timeout",
        str(timeout_ms),
        "-o",
        str(target_path),
    ]
    if width is not None:
        command.extend(["--width", str(width)])
    if height is not None:
        command.extend(["--height", str(height)])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise CameraCaptureError(
            message or f"libcamera-still exited with {completed.returncode}"
        )
    if not target_path.exists() or target_path.stat().st_size == 0:
        raise CameraCaptureError(f"libcamera did not create {target_path}")

    return CaptureResult(
        path=target_path,
        width=width or 0,
        height=height or 0,
        device_index=None,
        backend="libcamera",
    )


def _capture_with_raspistill(
    *,
    target_path: Path,
    width: Optional[int],
    height: Optional[int],
    warmup_seconds: float,
) -> CaptureResult:
    executable = shutil.which("raspistill")
    if executable is None:
        raise CameraCaptureError("raspistill command was not found")

    timeout_ms = max(1, int(warmup_seconds * 1000))
    command = [
        executable,
        "-n",
        "-t",
        str(timeout_ms),
        "-o",
        str(target_path),
    ]
    if width is not None:
        command.extend(["-w", str(width)])
    if height is not None:
        command.extend(["-h", str(height)])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise CameraCaptureError(
            message or f"raspistill exited with {completed.returncode}"
        )
    if not target_path.exists() or target_path.stat().st_size == 0:
        raise CameraCaptureError(f"raspistill did not create {target_path}")

    return CaptureResult(
        path=target_path,
        width=width or 0,
        height=height or 0,
        device_index=None,
        backend="raspistill",
    )
