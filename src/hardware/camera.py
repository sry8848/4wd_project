"""Camera capture helpers based on OpenCV.

Run this module through ``src/tools/test_camera.py`` on the Raspberry Pi.
The camera device index must be confirmed on the real car; do not assume the
reference project's device index is valid for this project.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Optional, Union


DEFAULT_CAPTURE_DIR = Path("captures")
DEFAULT_PHOTO_PREFIX = "photo"
DEFAULT_PHOTO_EXTENSION = ".jpg"


class CameraCaptureError(RuntimeError):
    """Raised when the camera cannot capture or save a frame."""


@dataclass(frozen=True)
class CaptureResult:
    """Metadata for one saved camera frame."""

    path: Path
    width: int
    height: int
    device_index: int


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

    try:
        import cv2
    except ImportError as exc:
        raise CameraCaptureError(
            "OpenCV is required for camera capture. Install python3-opencv or "
            "the cv2 package on the Raspberry Pi."
        ) from exc

    target_path = (
        Path(output_path)
        if output_path is not None
        else build_photo_path(output_dir, prefix, extension)
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

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
        )
    finally:
        camera.release()
