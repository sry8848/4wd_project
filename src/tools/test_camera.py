"""Manual camera capture test with visible progress output.

Examples:
    python3 src/tools/test_camera.py --backend opencv --device 1
    python3 src/tools/test_camera.py --backend opencv \
        --device-path /dev/v4l/by-id/...-video-index0
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
        "--backend",
        choices=("auto", "opencv", "libcamera", "raspistill"),
        default="auto",
        help=(
            "Capture backend. Use opencv for USB cameras; libcamera or "
            "raspistill for CSI cameras."
        ),
    )
    device_source = parser.add_mutually_exclusive_group()
    device_source.add_argument(
        "--device",
        type=int,
        default=None,
        help="OpenCV camera device index. Defaults to 0 when no path is given.",
    )
    device_source.add_argument(
        "--device-path",
        help=(
            "Stable V4L2 camera path, for example "
            "/dev/v4l/by-id/...-video-index0."
        ),
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
    """Capture one diagnostic frame from a numeric index or stable path."""

    args = parse_args()
    selected_device = (
        args.device_path
        if args.device_path is not None
        else (args.device if args.device is not None else 0)
    )
    output_path = args.output or build_photo_path(
        output_dir=args.output_dir,
        prefix=args.prefix,
        extension=args.extension,
    )

    print("Camera test started.", flush=True)
    print(f"Project root: {PROJECT_ROOT}", flush=True)
    print(f"Backend: {args.backend}", flush=True)
    print(f"Camera device: {selected_device}", flush=True)
    print(f"Output path: {output_path}", flush=True)

    try:
        print("Opening camera and capturing one frame...", flush=True)
        result = capture_photo(
            output_path=output_path,
            backend=args.backend,
            device_index=selected_device,
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
    print(f"Backend: {result.backend}")
    if result.device_index is not None:
        print(f"Device: {result.device_index}")
    if result.width and result.height:
        print(f"Resolution: {result.width}x{result.height}")
    print("Camera test finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
