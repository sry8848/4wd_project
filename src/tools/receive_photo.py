"""Receive photo files over TCP.

Run this on the computer that should receive images:

    python src/tools/receive_photo.py --host 0.0.0.0 --port 5001
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.network.image_transfer import ImageTransferError, receive_one_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Receive photo files over TCP.")
    parser.add_argument("--host", default="0.0.0.0", help="Local host/interface to bind.")
    parser.add_argument("--port", type=int, default=5001, help="TCP port to listen on.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("received_photos"),
        help="Directory for received photos.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="Optional receive timeout.",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Keep listening after each received photo.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"Photo receiver listening on {args.host}:{args.port}", flush=True)
    print(f"Saving photos to: {args.output_dir}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    while True:
        try:
            result = receive_one_file(
                host=args.host,
                port=args.port,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout_seconds,
            )
        except KeyboardInterrupt:
            print("Receiver stopped.")
            return 130
        except ImageTransferError as exc:
            print(f"Receive failed: {exc}", file=sys.stderr)
            return 1

        print(
            f"Received {result.size} bytes from {result.peer[0]}:{result.peer[1]} "
            f"-> {result.path}",
            flush=True,
        )

        if not args.keep_running:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
