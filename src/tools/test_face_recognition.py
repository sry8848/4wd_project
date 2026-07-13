"""Enroll and recognize faces with the Raspberry Pi car camera.

Examples::

    python3 src/tools/test_face_recognition.py enroll Alice --device 0
    python3 src/tools/test_face_recognition.py recognize --device 0
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.algorithms.face_recognition import (
    FaceRecognitionError,
    HaarFaceDetector,
    LocalFaceRecognizer,
)
from src.hardware.camera import CameraCaptureError, OpenCVCameraSession


DEFAULT_DATASET_DIR = Path("captures") / "faces"
SAFE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}$")


def parse_args() -> argparse.Namespace:
    """Parse face enrollment or recognition arguments."""

    parser = argparse.ArgumentParser(
        description="Enroll local face samples or recognize a registered person."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enroll = subparsers.add_parser("enroll", help="Capture reference images for one person.")
    enroll.add_argument("name", help="Person label (letters, digits, Chinese, '_' or '-').")
    enroll.add_argument("--count", type=int, default=10, help="Number of accepted samples.")
    enroll.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Minimum seconds between accepted samples.",
    )

    recognize = subparsers.add_parser("recognize", help="Recognize registered people.")
    recognize.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        help="Maximum LBPH distance for a known face; lower is stricter.",
    )
    recognize.add_argument(
        "--confirm-frames",
        type=int,
        default=3,
        help="Consecutive matching frames required before success.",
    )

    for subparser in (enroll, recognize):
        subparser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_DIR)
        subparser.add_argument("--device", type=int, default=0)
        subparser.add_argument("--width", type=int, default=640)
        subparser.add_argument("--height", type=int, default=480)
        subparser.add_argument("--timeout", type=float, default=20.0)
        subparser.add_argument("--warmup-seconds", type=float, default=0.5)
        subparser.add_argument(
            "--cascade",
            type=Path,
            help="Optional Haar XML path; OpenCV's bundled cascade is the default.",
        )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Validate numeric limits and the optional enrollment label.

    Args:
        args: Parsed command-line namespace.
    """

    if args.width <= 0 or args.height <= 0:
        raise ValueError("--width and --height must be greater than 0")
    if args.timeout <= 0 or args.warmup_seconds < 0:
        raise ValueError("--timeout must be greater than 0 and warmup must not be negative")
    if args.command == "enroll":
        if not SAFE_LABEL_PATTERN.fullmatch(args.name):
            raise ValueError("name must be 1-32 letters, digits, Chinese, '_' or '-'")
        if args.count <= 0 or args.interval < 0:
            raise ValueError("--count must be greater than 0 and --interval must not be negative")
    else:
        if args.threshold <= 0 or args.confirm_frames <= 0:
            raise ValueError("--threshold and --confirm-frames must be greater than 0")


def enroll(args: argparse.Namespace, detector: HaarFaceDetector) -> int:
    """Capture full frames that contain exactly one frontal face.

    Args:
        args: Validated enrollment settings.
        detector: Initialized Haar face detector.
    """

    import cv2

    person_dir = args.dataset / args.name
    person_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.timeout
    accepted = 0
    next_capture_time = 0.0

    print(f"Enrollment started for {args.name!r}; look straight at the camera.")
    print(f"Saving {args.count} samples under {person_dir}")
    with _open_camera(args) as camera:
        while accepted < args.count and time.monotonic() < deadline:
            frame = camera.read_frame()
            boxes = detector.detect(frame)
            now = time.monotonic()
            if len(boxes) != 1 or now < next_capture_time:
                continue

            # 1. Save the full frame so dataset loading repeats normal detection.
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            output_path = person_dir / f"sample_{timestamp}.jpg"
            if not cv2.imwrite(str(output_path), frame):
                raise FaceRecognitionError(f"Failed to save face sample: {output_path}")
            # 2. Space samples out so small pose and expression changes are captured.
            accepted += 1
            next_capture_time = now + args.interval
            print(f"Accepted sample {accepted}/{args.count}: {output_path}", flush=True)

    if accepted < args.count:
        print(
            f"Enrollment timed out after {accepted}/{args.count} samples; "
            "ensure exactly one frontal face is visible.",
            file=sys.stderr,
        )
        return 1
    print("Enrollment complete. Run the recognize command next.")
    return 0


def recognize(args: argparse.Namespace, detector: HaarFaceDetector) -> int:
    """Recognize a registered person for consecutive camera frames.

    Args:
        args: Validated recognition settings.
        detector: Initialized Haar face detector.
    """

    recognizer = LocalFaceRecognizer(detector=detector, threshold=args.threshold)
    dataset = recognizer.load_dataset(args.dataset)
    print(
        f"Loaded {dataset.total_samples} samples for {', '.join(recognizer.labels)} "
        f"({dataset.skipped_images} skipped)."
    )
    print(
        f"Recognition started; threshold={args.threshold:.3f}, "
        f"confirmation={args.confirm_frames} frames."
    )

    deadline = time.monotonic() + args.timeout
    candidate = None
    consecutive = 0
    best_unknown_distance = float("inf")
    with _open_camera(args) as camera:
        while time.monotonic() < deadline:
            matches = recognizer.recognize(camera.read_frame())
            known_matches = [match for match in matches if match.label is not None]
            if not known_matches:
                candidate = None
                consecutive = 0
                if matches:
                    best_unknown_distance = min(
                        best_unknown_distance, min(match.distance for match in matches)
                    )
                continue

            # 1. Track the strongest known face from this frame.
            best_match = min(known_matches, key=lambda match: match.distance)
            if best_match.label == candidate:
                consecutive += 1
            else:
                candidate = best_match.label
                consecutive = 1
            print(
                f"Candidate: {candidate} distance={best_match.distance:.3f} "
                f"confirmation={consecutive}/{args.confirm_frames}",
                flush=True,
            )
            # 2. Require consecutive agreement to avoid one-frame false positives.
            if consecutive >= args.confirm_frames:
                print(f"Recognized: {candidate}")
                return 0

    detail = (
        f" Best unknown distance: {best_unknown_distance:.3f}."
        if best_unknown_distance < float("inf")
        else " No face was detected."
    )
    print(f"No registered person was confirmed before timeout.{detail}", file=sys.stderr)
    return 1


def _open_camera(args: argparse.Namespace) -> OpenCVCameraSession:
    """Create the shared camera session from validated CLI parameters."""

    return OpenCVCameraSession(
        device_index=args.device,
        width=args.width,
        height=args.height,
        warmup_frames=5,
        warmup_seconds=args.warmup_seconds,
    )


def main() -> int:
    """Run enrollment or recognition and map expected errors to exit codes."""

    args = parse_args()
    try:
        validate_args(args)
        detector = HaarFaceDetector(cascade_path=args.cascade)
        if args.command == "enroll":
            return enroll(args, detector)
        return recognize(args, detector)
    except (CameraCaptureError, FaceRecognitionError, ValueError) as exc:
        print(f"Face {args.command} failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nFace operation cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
