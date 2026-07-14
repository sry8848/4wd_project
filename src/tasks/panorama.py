"""Stitch source photos captured by the car-turn panorama tool."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union


PathLike = Union[str, Path]


class PanoramaError(RuntimeError):
    """Raised when panorama stitching cannot produce an output image."""


def stitch_images(
    image_paths: Sequence[PathLike],
    output_path: PathLike,
    *,
    confidence_threshold: float = 0.01,
) -> Path:
    """Stitch car-turn source photos into one panorama image.

    Args:
        image_paths: Source image paths in left-to-right capture order.
        output_path: Final panorama image path.
        confidence_threshold: OpenCV Stitcher confidence threshold.

    Steps:
        1. Require at least two readable source images.
        2. Run the available OpenCV panorama stitcher.
        3. Create the output directory and write the completed panorama.
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


def _create_stitcher(cv2):
    """Create an OpenCV Stitcher across common OpenCV versions."""

    if hasattr(cv2, "Stitcher_create"):
        if hasattr(cv2, "Stitcher_PANORAMA"):
            return cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
        return cv2.Stitcher_create()
    if hasattr(cv2, "createStitcher"):
        return cv2.createStitcher(False)
    raise PanoramaError("current OpenCV build does not provide Stitcher")


def _format_stitch_error(status: int) -> str:
    """Convert an OpenCV Stitcher status into an actionable error."""

    hints = {
        1: "need more matching features or more overlap between photos",
        2: "homography estimation failed; try slower movement or more overlap",
        3: "camera parameter adjustment failed; try fewer blur/exposure changes",
    }
    hint = hints.get(status, "unknown OpenCV Stitcher error")
    return f"panorama stitching failed with status {status}: {hint}"
