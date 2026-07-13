"""Offline face detection and local LBPH-style face recognition.

Reference images are arranged as ``DATASET/PERSON/*.jpg``.  The implementation
uses OpenCV's bundled Haar cascade to locate faces and a small NumPy Local
Binary Pattern Histogram descriptor to compare identities.  It deliberately
does not depend on cloud credentials or the optional ``cv2.face`` module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


PathLike = Union[str, Path]
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


class FaceRecognitionError(RuntimeError):
    """Raised when face recognition cannot be initialized or trained."""


@dataclass(frozen=True)
class FaceBox:
    """Pixel coordinates of one detected face.

    Args:
        x: Left edge in pixels.
        y: Top edge in pixels.
        width: Face width in pixels.
        height: Face height in pixels.
    """

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class FaceMatch:
    """Recognition result for one detected face.

    Args:
        box: Location of the face in the input frame.
        label: Dataset directory name, or ``None`` for an unknown person.
        distance: Nearest LBPH distance; smaller values are more similar.
    """

    box: FaceBox
    label: Optional[str]
    distance: float


@dataclass(frozen=True)
class DatasetLoadResult:
    """Summary of reference images accepted from a dataset directory."""

    samples_by_label: Dict[str, int]
    skipped_images: int

    @property
    def total_samples(self) -> int:
        """Return the number of usable reference images."""

        return sum(self.samples_by_label.values())


class HaarFaceDetector:
    """Detect frontal faces with OpenCV's bundled Haar cascade.

    Args:
        cascade_path: Optional explicit Haar XML file. When omitted, OpenCV's
            packaged ``haarcascade_frontalface_default.xml`` is used.
        min_face_size: Minimum ``(width, height)`` accepted by the detector.
        classifier: Optional compatible classifier for dependency injection.
        cv2_module: Optional imported OpenCV module for dependency injection.
    """

    def __init__(
        self,
        cascade_path: Optional[PathLike] = None,
        *,
        min_face_size: Tuple[int, int] = (60, 60),
        classifier: Optional[object] = None,
        cv2_module: Optional[object] = None,
    ):
        if min_face_size[0] <= 0 or min_face_size[1] <= 0:
            raise ValueError("min_face_size values must be greater than 0")

        self._cv2 = cv2_module or _import_cv2()
        self.min_face_size = min_face_size
        if classifier is not None:
            self._classifier = classifier
            return

        # 1. Resolve the cascade from OpenCV unless the caller supplied one.
        resolved_path = Path(cascade_path) if cascade_path else _default_cascade_path(self._cv2)
        if not resolved_path.is_file():
            raise FaceRecognitionError(f"Haar cascade file not found: {resolved_path}")

        # 2. Load it once so every camera frame reuses the same classifier.
        self._classifier = self._cv2.CascadeClassifier(str(resolved_path))
        if self._classifier.empty():
            raise FaceRecognitionError(f"Failed to load Haar cascade: {resolved_path}")

    def detect(self, frame) -> List[FaceBox]:
        """Return detected faces, largest first.

        Args:
            frame: OpenCV BGR or grayscale image.
        """

        if frame is None:
            raise ValueError("frame must not be None")

        # 1. Normalize contrast in grayscale for steadier indoor detection.
        gray = _to_grayscale(self._cv2, frame)
        gray = self._cv2.equalizeHist(gray)
        # 2. Detect and convert OpenCV tuples to stable project data objects.
        raw_boxes = self._classifier.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=self.min_face_size,
        )
        boxes = [FaceBox(*(int(value) for value in box)) for box in raw_boxes]
        return sorted(boxes, key=lambda box: box.width * box.height, reverse=True)


class LocalFaceRecognizer:
    """Recognize detected faces against locally stored reference images.

    Args:
        detector: Face detector shared by dataset loading and live recognition.
        threshold: Maximum mean chi-square distance accepted as a known face.
        cv2_module: Optional imported OpenCV module for dependency injection.
        numpy_module: Optional imported NumPy module for dependency injection.
    """

    def __init__(
        self,
        detector: Optional[HaarFaceDetector] = None,
        *,
        threshold: float = 0.30,
        cv2_module: Optional[object] = None,
        numpy_module: Optional[object] = None,
    ):
        if threshold <= 0:
            raise ValueError("threshold must be greater than 0")
        self._cv2 = cv2_module or _import_cv2()
        self._np = numpy_module or _import_numpy()
        self.detector = detector or HaarFaceDetector(cv2_module=self._cv2)
        self.threshold = threshold
        self._references: Dict[str, List[object]] = {}

    @property
    def labels(self) -> Tuple[str, ...]:
        """Return trained person labels in sorted order."""

        return tuple(sorted(self._references))

    def load_dataset(self, dataset_dir: PathLike) -> DatasetLoadResult:
        """Load labeled reference images from ``DATASET/PERSON`` directories.

        Args:
            dataset_dir: Root directory containing one child directory per
                person and one or more face images inside each child.

        Returns:
            Counts of accepted and skipped images.
        """

        root = Path(dataset_dir)
        if not root.is_dir():
            raise FaceRecognitionError(f"Face dataset directory not found: {root}")

        references: Dict[str, List[object]] = {}
        skipped = 0
        # 1. Treat each direct child directory name as the person's label.
        for person_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            descriptors = []
            # 2. Use the largest detected face from every readable image.
            for image_path in sorted(person_dir.iterdir()):
                if image_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                    continue
                image = self._cv2.imread(str(image_path))
                if image is None:
                    skipped += 1
                    continue
                boxes = self.detector.detect(image)
                if not boxes:
                    skipped += 1
                    continue
                descriptors.append(self.describe_face(image, boxes[0]))
            if descriptors:
                references[person_dir.name] = descriptors

        if not references:
            raise FaceRecognitionError(
                f"No usable face images found under {root}; enroll clear frontal faces first"
            )
        # 3. Replace training state only after a valid dataset is fully built.
        self._references = references
        return DatasetLoadResult(
            samples_by_label={label: len(items) for label, items in references.items()},
            skipped_images=skipped,
        )

    def describe_face(self, frame, box: FaceBox):
        """Build a normalized LBPH descriptor for one face region.

        Args:
            frame: OpenCV BGR or grayscale image.
            box: Face region within ``frame``.
        """

        if frame is None:
            raise ValueError("frame must not be None")
        _validate_box(frame, box)
        face = frame[box.y : box.y + box.height, box.x : box.x + box.width]
        gray = _to_grayscale(self._cv2, face)
        normalized = self._cv2.resize(gray, (96, 96))
        normalized = self._cv2.equalizeHist(normalized)
        return _lbph_descriptor(self._np, normalized, grid_size=(8, 8))

    def recognize(self, frame) -> List[FaceMatch]:
        """Detect and identify every visible face in one frame.

        Args:
            frame: OpenCV BGR or grayscale image.

        Returns:
            Face matches ordered from the largest detected face to the smallest.
        """

        if not self._references:
            raise FaceRecognitionError("Face recognizer has no loaded dataset")

        matches = []
        # 1. Describe each detected face independently.
        for box in self.detector.detect(frame):
            descriptor = self.describe_face(frame, box)
            best_label = None
            best_distance = float("inf")
            # 2. Use nearest-sample matching across every registered person.
            for label, references in self._references.items():
                for reference in references:
                    distance = _chi_square_distance(self._np, descriptor, reference)
                    if distance < best_distance:
                        best_label = label
                        best_distance = distance
            # 3. Reject weak matches instead of forcing an incorrect identity.
            label = best_label if best_distance <= self.threshold else None
            matches.append(FaceMatch(box=box, label=label, distance=best_distance))
        return matches


def _lbph_descriptor(np, gray, *, grid_size: Tuple[int, int]):
    """Return concatenated per-cell Local Binary Pattern histograms."""

    if getattr(gray, "ndim", 0) != 2 or min(gray.shape) < 3:
        raise ValueError("gray face image must be a two-dimensional image at least 3x3")

    center = gray[1:-1, 1:-1]
    neighbors = (
        gray[:-2, :-2],
        gray[:-2, 1:-1],
        gray[:-2, 2:],
        gray[1:-1, 2:],
        gray[2:, 2:],
        gray[2:, 1:-1],
        gray[2:, :-2],
        gray[1:-1, :-2],
    )
    lbp = np.zeros(center.shape, dtype=np.uint8)
    for bit, neighbor in enumerate(neighbors):
        lbp |= ((neighbor >= center).astype(np.uint8) << bit)

    histograms = []
    for row in np.array_split(lbp, grid_size[1], axis=0):
        for cell in np.array_split(row, grid_size[0], axis=1):
            histogram = np.bincount(cell.ravel(), minlength=256).astype(np.float32)
            total = float(histogram.sum())
            if total:
                histogram /= total
            histograms.append(histogram)
    return np.concatenate(histograms)


def _chi_square_distance(np, first, second) -> float:
    """Return mean chi-square distance between equal-length LBPH descriptors."""

    if first.shape != second.shape:
        raise ValueError("face descriptors must have matching shapes")
    denominator = first + second + 1e-10
    raw_distance = 0.5 * np.sum(((first - second) ** 2) / denominator)
    cells = max(1, int(first.size // 256))
    return float(raw_distance / cells)


def _validate_box(frame, box: FaceBox) -> None:
    """Validate that a face box is non-empty and inside an image."""

    height, width = frame.shape[:2]
    if box.width <= 0 or box.height <= 0:
        raise ValueError("face box dimensions must be greater than 0")
    if box.x < 0 or box.y < 0 or box.x + box.width > width or box.y + box.height > height:
        raise ValueError("face box must be inside the image")


def _to_grayscale(cv2, frame):
    """Convert a BGR frame to grayscale while accepting grayscale input."""

    if getattr(frame, "ndim", 0) == 2:
        return frame
    if getattr(frame, "ndim", 0) == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    raise ValueError("frame must be a grayscale or BGR image")


def _default_cascade_path(cv2) -> Path:
    """Resolve OpenCV's packaged frontal-face cascade path."""

    data = getattr(cv2, "data", None)
    haarcascades = getattr(data, "haarcascades", None)
    if not haarcascades:
        raise FaceRecognitionError(
            "This OpenCV build does not expose cv2.data.haarcascades; pass --cascade"
        )
    return Path(haarcascades) / "haarcascade_frontalface_default.xml"


def _import_cv2():
    """Import OpenCV with a project-specific installation error."""

    try:
        import cv2
    except ImportError as exc:
        raise FaceRecognitionError(
            "OpenCV is not installed; install it with: sudo apt install python3-opencv"
        ) from exc
    return cv2


def _import_numpy():
    """Import NumPy with a project-specific installation error."""

    try:
        import numpy
    except ImportError as exc:
        raise FaceRecognitionError(
            "NumPy is not installed; install it with: sudo apt install python3-numpy"
        ) from exc
    return numpy
