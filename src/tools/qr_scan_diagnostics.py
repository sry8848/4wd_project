"""Shared diagnostic snapshot helpers for manual QR-code scan tools."""

from __future__ import annotations

from pathlib import Path

from src.hardware.camera import build_photo_path


DEFAULT_QR_DIAGNOSTIC_DIR = Path("captures/qr_debug")


def save_qr_diagnostic_snapshot(
    camera,
    frame,
    *,
    output_dir=DEFAULT_QR_DIAGNOSTIC_DIR,
    prefix="qr_timeout",
):
    """Save the final available scan frame and return its quality diagnostics.

    Args:
        camera: Active OpenCVCameraSession owning the OpenCV encoder.
        frame: Last image available to the scan task.
        output_dir: Directory for the timestamped JPEG.
        prefix: Filename prefix distinguishing timeout and success snapshots.

    Steps:
    1. Return None when scanning ended before any frame was available.
    2. Allocate a timestamped path below the requested diagnostic directory.
    3. Delegate image writing and metrics to the camera hardware boundary.
    """

    if frame is None:
        return None
    output_path = build_photo_path(output_dir=output_dir, prefix=prefix)
    return camera.save_diagnostic_frame(output_path, frame)


def format_qr_snapshot_diagnostics(result) -> str:
    """Format saved-frame resolution, brightness and sharpness for the terminal."""

    return (
        f"path={result.path}, resolution={result.width}x{result.height}, "
        f"brightness={result.mean_brightness:.1f}/255, "
        f"sharpness={result.sharpness:.1f}"
    )
