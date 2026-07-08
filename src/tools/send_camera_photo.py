"""Capture one photo and send it to a TCP receiver.

Run the receiver on your computer first, then run this on the Raspberry Pi:

    python3 src/tools/send_camera_photo.py --host YOUR_COMPUTER_IP
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware.camera import CameraCaptureError, build_photo_path, capture_photo
from src.network.image_transfer import ImageTransferError, send_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and send one photo.")
    parser.add_argument("--host", required=True, help="Receiver computer IP address.")
    parser.add_argument("--port", type=int, default=5001, help="Receiver TCP port.")
    parser.add_argument(
        "--backend",
        choices=("auto", "opencv", "libcamera", "raspistill"),
        default="auto",
        help="Capture backend.",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=0,
        help="OpenCV camera device index. Ignored by libcamera backend.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Local photo path.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("captures"),
        help="Local directory for timestamped photo output.",
    )
    parser.add_argument("--prefix", default="photo", help="Photo filename prefix.")
    parser.add_argument("--extension", default=".jpg", help="Photo extension.")
    parser.add_argument("--width", type=int, default=None, help="Requested frame width.")
    parser.add_argument("--height", type=int, default=None, help="Requested frame height.")
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=5,
        help="OpenCV frames to discard before saving.",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.5,
        help="Camera warmup delay.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="TCP connect/send timeout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output or build_photo_path(
        output_dir=args.output_dir,
        prefix=args.prefix,
        extension=args.extension,
    )

    print("Capture + send started.", flush=True)
    print(f"Receiver: {args.host}:{args.port}", flush=True)
    print(f"Local photo path: {output_path}", flush=True)

    try:
        print("Capturing photo...", flush=True)
        capture_result = capture_photo(
            output_path=output_path,
            backend=args.backend,
            device_index=args.device,
            width=args.width,
            height=args.height,
            warmup_frames=args.warmup_frames,
            warmup_seconds=args.warmup_seconds,
        )
        print(f"Photo saved: {capture_result.path}", flush=True)
        print(f"Capture backend: {capture_result.backend}", flush=True)

        print("Sending photo over TCP...", flush=True)
        send_result = send_file(
            capture_result.path,
            host=args.host,
            port=args.port,
            timeout_seconds=args.timeout_seconds,
        )
    except CameraCaptureError as exc:
        print(f"Camera capture failed: {exc}", file=sys.stderr)
        return 1
    except ImageTransferError as exc:
        print(f"TCP transfer failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Sent {send_result.size} bytes to "
        f"{send_result.host}:{send_result.port}",
        flush=True,
    )
    print("Capture + send finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
