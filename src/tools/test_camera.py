"""Manual camera capture test.

Run on the Raspberry Pi from the project root:

    python3 src/tools/test_camera.py --device 0

If the camera cannot be opened, try another device index and check whether a
video streaming service is already using the camera.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware.camera import CameraCaptureError, build_photo_path, capture_photo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture one camera photo.")
    parser.add_argument(
        "--device",
        type=int,
        default=0,
        help="OpenCV camera device index, usually 0 or 1.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Exact output image path. Overrides --output-dir and --prefix.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("captures"),
        help="Directory for timestamped photo output.",
    )
    parser.add_argument(
        "--prefix",
        default="photo",
        help="Filename prefix for timestamped photo output.",
    )
    parser.add_argument(
        "--extension",
        default=".jpg",
        help="Image extension used for timestamped output.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Optional requested frame width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Optional requested frame height.",
    )
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=5,
        help="Frames to discard before saving.",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.5,
        help="Delay after opening the camera.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output or build_photo_path(
        output_dir=args.output_dir,
        prefix=args.prefix,
        extension=args.extension,
    )

    try:
        result = capture_photo(
            output_path=output_path,
            device_index=args.device,
            width=args.width,
            height=args.height,
            warmup_frames=args.warmup_frames,
            warmup_seconds=args.warmup_seconds,
        )
    except CameraCaptureError as exc:
        print(f"Camera capture failed: {exc}", file=sys.stderr)
        print(
            "Hint: confirm the device index and stop any mjpg/video service "
            "that may already own the camera.",
            file=sys.stderr,
        )
        return 1

    print(f"Saved photo: {result.path}")
    print(
        f"Device: {result.device_index}, "
        f"resolution: {result.width}x{result.height}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
