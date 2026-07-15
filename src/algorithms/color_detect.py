"""HSV-based color-region detection for images and camera frames.

The algorithm has no GPIO or camera ownership. Callers provide an OpenCV BGR
frame and receive structured detections that can be used by tools or tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


HSVTriplet = Tuple[int, int, int]
HSVInterval = Tuple[HSVTriplet, HSVTriplet]
BoundingBox = Tuple[int, int, int, int]
Point = Tuple[int, int]


class ColorDetectionError(RuntimeError):
    """Raised when color detection cannot be initialized or executed."""


@dataclass(frozen=True)
class ColorSpec:
    """HSV ranges and drawing color for one supported color.

    Args:
        name: Stable English color name used by command-line tools.
        hsv_intervals: One or more inclusive OpenCV HSV threshold ranges.
        display_bgr: BGR color used to annotate a detected region.
    """

    name: str
    hsv_intervals: Tuple[HSVInterval, ...]
    display_bgr: Tuple[int, int, int]


@dataclass(frozen=True)
class ColorRegion:
    """One connected target-color region detected in a frame.

    Args:
        color: Stable English color name.
        area: Contour area in pixels.
        coverage: Contour area divided by the full frame area.
        center: Region center as ``(x, y)`` pixels.
        bounding_box: Region rectangle as ``(x, y, width, height)`` pixels.
    """

    color: str
    area: float
    coverage: float
    center: Point
    bounding_box: BoundingBox


@dataclass(frozen=True)
class ColorDetectionResult:
    """Structured color detection output for one frame."""

    width: int
    height: int
    regions: Tuple[ColorRegion, ...]

    @property
    def dominant_color(self) -> Optional[str]:
        """Return the color of the largest detected region, if any."""

        return self.regions[0].color if self.regions else None


DEFAULT_COLOR_SPECS: Dict[str, ColorSpec] = {
    # Red wraps around the 0/179 boundary in OpenCV's hue representation.
    "red": ColorSpec(
        name="red",
        hsv_intervals=(
            ((0, 100, 80), (10, 255, 255)),
            ((170, 100, 80), (179, 255, 255)),
        ),
        display_bgr=(0, 0, 255),
    ),
    "green": ColorSpec(
        name="green",
        hsv_intervals=(((40, 80, 60), (85, 255, 255)),),
        display_bgr=(0, 255, 0),
    ),
    "blue": ColorSpec(
        name="blue",
        hsv_intervals=(((90, 100, 60), (130, 255, 255)),),
        display_bgr=(255, 0, 0),
    ),
    "yellow": ColorSpec(
        name="yellow",
        hsv_intervals=(((20, 100, 100), (35, 255, 255)),),
        display_bgr=(0, 255, 255),
    ),
}


class ColorDetector:
    """Detect configured HSV color regions in OpenCV BGR frames.

    Args:
        colors: Supported color names to detect. Defaults to all colors.
        min_area: Smallest contour area accepted, in pixels.
        morphology_kernel_size: Odd kernel width used to remove mask noise.
        color_specs: Optional replacement specifications for field calibration.
        cv2_module: Optional OpenCV module for dependency injection.
        numpy_module: Optional NumPy module for dependency injection.
    """

    def __init__(
        self,
        *,
        colors: Optional[Sequence[str]] = None,
        min_area: float = 1500.0,
        morphology_kernel_size: int = 5,
        color_specs: Optional[Dict[str, ColorSpec]] = None,
        cv2_module=None,
        numpy_module=None,
    ):
        if min_area <= 0:
            raise ValueError("min_area must be greater than 0")
        if morphology_kernel_size < 1 or morphology_kernel_size % 2 == 0:
            raise ValueError("morphology_kernel_size must be a positive odd integer")

        self._cv2, self._numpy = _load_image_dependencies(
            cv2_module=cv2_module,
            numpy_module=numpy_module,
        )
        available_specs = color_specs or DEFAULT_COLOR_SPECS
        selected_names = list(colors) if colors is not None else list(available_specs)
        selected_names = list(dict.fromkeys(name.lower() for name in selected_names))
        if not selected_names:
            raise ValueError("at least one color must be selected")

        unknown = [name for name in selected_names if name not in available_specs]
        if unknown:
            supported = ", ".join(available_specs)
            raise ValueError(
                "unsupported color(s): {0}; supported colors: {1}".format(
                    ", ".join(unknown), supported
                )
            )

        self.color_specs = tuple(available_specs[name] for name in selected_names)
        self.min_area = float(min_area)
        self.morphology_kernel_size = morphology_kernel_size

    def detect(self, frame) -> ColorDetectionResult:
        """Detect target colors in one OpenCV BGR image.

        Args:
            frame: Non-empty OpenCV BGR image with three channels.

        Returns:
            Frame dimensions and regions sorted from largest to smallest.
        """

        if frame is None or not hasattr(frame, "shape"):
            raise ValueError("frame must be a non-empty OpenCV BGR image")
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            raise ValueError("frame must have exactly three BGR channels")
        height, width = frame.shape[:2]
        if width <= 0 or height <= 0:
            raise ValueError("frame must be a non-empty OpenCV BGR image")

        # 1. Convert once; every configured color shares this HSV frame.
        hsv = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2HSV)
        kernel = self._numpy.ones(
            (self.morphology_kernel_size, self.morphology_kernel_size),
            dtype=self._numpy.uint8,
        )
        regions: List[ColorRegion] = []

        # 2. Build and clean one mask per color, combining wrapped hue ranges.
        for spec in self.color_specs:
            mask = None
            for lower, upper in spec.hsv_intervals:
                interval_mask = self._cv2.inRange(
                    hsv,
                    self._numpy.array(lower, dtype=self._numpy.uint8),
                    self._numpy.array(upper, dtype=self._numpy.uint8),
                )
                mask = (
                    interval_mask
                    if mask is None
                    else self._cv2.bitwise_or(mask, interval_mask)
                )

            mask = self._cv2.morphologyEx(mask, self._cv2.MORPH_OPEN, kernel)
            mask = self._cv2.morphologyEx(mask, self._cv2.MORPH_CLOSE, kernel)
            contours_result = self._cv2.findContours(
                mask, self._cv2.RETR_EXTERNAL, self._cv2.CHAIN_APPROX_SIMPLE
            )
            contours = contours_result[-2]

            # 3. Reject small noise and convert valid contours to stable data.
            for contour in contours:
                area = float(self._cv2.contourArea(contour))
                if area < self.min_area:
                    continue
                x, y, box_width, box_height = self._cv2.boundingRect(contour)
                regions.append(
                    ColorRegion(
                        color=spec.name,
                        area=area,
                        coverage=area / float(width * height),
                        center=(x + box_width // 2, y + box_height // 2),
                        bounding_box=(x, y, box_width, box_height),
                    )
                )

        regions.sort(key=lambda region: region.area, reverse=True)
        return ColorDetectionResult(
            width=int(width),
            height=int(height),
            regions=tuple(regions),
        )

    def annotate(self, frame, result: ColorDetectionResult):
        """Return a copy of the frame with boxes and labels for each region.

        Args:
            frame: Original OpenCV BGR frame.
            result: Detection result produced from that frame.
        """

        annotated = frame.copy()
        spec_by_name = {spec.name: spec for spec in self.color_specs}

        # Draw a stable English label because OpenCV's default font lacks CJK.
        for region in result.regions:
            x, y, width, height = region.bounding_box
            display_bgr = spec_by_name[region.color].display_bgr
            self._cv2.rectangle(
                annotated, (x, y), (x + width, y + height), display_bgr, 2
            )
            self._cv2.circle(annotated, region.center, 4, display_bgr, -1)
            label = "{0} {1:.1f}%".format(region.color, region.coverage * 100.0)
            text_y = max(18, y - 6)
            self._cv2.putText(
                annotated,
                label,
                (x, text_y),
                self._cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                display_bgr,
                2,
                self._cv2.LINE_AA,
            )
        return annotated


def _load_image_dependencies(*, cv2_module=None, numpy_module=None):
    """Import OpenCV and NumPy with a project-specific installation error."""

    try:
        if cv2_module is None:
            import cv2 as cv2_module
        if numpy_module is None:
            import numpy as numpy_module
    except ImportError as exc:
        raise ColorDetectionError(
            "OpenCV and NumPy are required; on Raspberry Pi install them with: "
            "sudo apt install python3-opencv python3-numpy"
        ) from exc
    return cv2_module, numpy_module
