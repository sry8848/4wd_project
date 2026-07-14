"""Manual, time-limited QR-code recognition test for the car camera."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.algorithms.qr_detect import (
    QRCodeFormatError,
    QRCodeRecognitionError,
    QRCodeRecognizer,
    parse_qr_payload,
)
from src.hardware.camera import CameraCaptureError, OpenCVCameraSession
from src.tools.qr_scan_diagnostics import (
    DEFAULT_QR_DIAGNOSTIC_DIR,
    format_qr_snapshot_diagnostics,
    save_qr_diagnostic_snapshot,
)


def parse_args() -> argparse.Namespace:
    """Parse camera and scan-duration arguments."""

    parser = argparse.ArgumentParser(
        description="Scan a TYPE:ID QR code with the OpenCV camera."
    )
    camera_source = parser.add_mutually_exclusive_group()
    camera_source.add_argument(
        "--device",
        type=int,
        default=0,
        help="OpenCV camera device index, usually 0 or 1.",
    )
    camera_source.add_argument(
        "--device-path",
        type=Path,
        help="Stable V4L2 camera path, for example /dev/v4l/by-id/...-video-index0.",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Maximum scan time in seconds.",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.5,
        help="Camera exposure warm-up time in seconds.",
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=2.0,
        help="Print scan frame progress at this interval in seconds.",
    )
    parser.add_argument(
        "--diagnostic-dir",
        type=Path,
        default=DEFAULT_QR_DIAGNOSTIC_DIR,
        help="Directory used for timestamped timeout/success diagnostic JPEGs.",
    )
    parser.add_argument(
        "--save-success-photo",
        action="store_true",
        help="Also save the frame that successfully decoded the QR code.",
    )
    return parser.parse_args()


def save_and_report_snapshot(camera, frame, output_dir, prefix) -> None:
    """Best-effort save of one QR scan frame without changing scan outcome.

    Args:
        camera: Active OpenCVCameraSession.
        frame: Last frame passed to QRCodeRecognizer.
        output_dir: Destination directory for the timestamped JPEG.
        prefix: ``qr_timeout`` or ``qr_success``.

    Steps:
    1. Skip with an explicit message if no frame was ever read.
    2. Save and print image-quality metrics.
    3. Report write failures without hiding the original scan result.
    """

    try:
        result = save_qr_diagnostic_snapshot(
            camera,
            frame,
            output_dir=output_dir,
            prefix=prefix,
        )
    except CameraCaptureError as exc:
        print(f"Failed to save diagnostic snapshot: {exc}", file=sys.stderr)
        return
    if result is None:
        print("No camera frame was available for a diagnostic snapshot.", file=sys.stderr)
        return
    print(f"Diagnostic snapshot: {format_qr_snapshot_diagnostics(result)}", flush=True)


def main() -> int:
    """Scan until one valid project QR code is read or timeout expires."""

    args = parse_args()
    if args.timeout <= 0:
        print("--timeout must be greater than 0", file=sys.stderr)
        return 2
    if args.progress_interval <= 0:
        print("--progress-interval must be greater than 0", file=sys.stderr)
        return 2

    print("QR-code scan started.", flush=True)
    print(f"Expected format: TYPE:ID (example: TOLL:GATE1)", flush=True)
    selected_device = (
        str(args.device_path) if args.device_path is not None else args.device
    )
    print(f"Camera: device={selected_device}, {args.width}x{args.height}", flush=True)
    print(f"Timeout: {args.timeout:.1f} seconds", flush=True)

    started_at = time.monotonic()
    deadline = started_at + args.timeout
    next_progress_at = started_at + args.progress_interval
    frames_scanned = 0
    last_frame = None
    reported_invalid_texts = set()

    try:
        recognizer = QRCodeRecognizer()
        # The context manager always releases the camera, including on Ctrl+C.
        with OpenCVCameraSession(
            device_index=selected_device,
            width=args.width,
            height=args.height,
            warmup_frames=5,
            warmup_seconds=args.warmup_seconds,
        ) as camera:
            while time.monotonic() < deadline:
                # 1. Read the latest camera frame.
                frame = camera.read_frame()
                last_frame = frame
                frames_scanned += 1
                # 2. Decode every QR code visible in this frame.
                for raw_text in recognizer.decode(frame):
                    try:
                        payload = parse_qr_payload(raw_text)
                    except QRCodeFormatError as exc:
                        if raw_text not in reported_invalid_texts:
                            print(
                                f"Ignored invalid QR code {raw_text!r}: {exc}",
                                file=sys.stderr,
                                flush=True,
                            )
                            reported_invalid_texts.add(raw_text)
                        continue

                    # 3. Stop after the first valid result; future tasks can
                    # dispatch behavior using payload.qr_type and identifier.
                    print("Valid QR code detected.")
                    print(f"Raw text: {payload.raw_text}")
                    print(f"Type: {payload.qr_type}")
                    print(f"Identifier: {payload.identifier}")
                    print(
                        f"Scan statistics: frames={frames_scanned}, "
                        f"elapsed={time.monotonic() - started_at:.1f}s"
                    )
                    if args.save_success_photo:
                        save_and_report_snapshot(
                            camera,
                            last_frame,
                            args.diagnostic_dir,
                            "qr_success",
                        )
                    return 0

                now = time.monotonic()
                if now >= next_progress_at:
                    height, width = frame.shape[:2]
                    print(
                        f"Scanning: frames={frames_scanned}, "
                        f"elapsed={now - started_at:.1f}s, "
                        f"resolution={width}x{height}",
                        flush=True,
                    )
                    next_progress_at = now + args.progress_interval

            print(
                f"Scan statistics: frames={frames_scanned}, "
                f"elapsed={time.monotonic() - started_at:.1f}s",
                flush=True,
            )
            save_and_report_snapshot(
                camera,
                last_frame,
                args.diagnostic_dir,
                "qr_timeout",
            )

    except (CameraCaptureError, QRCodeRecognitionError, ValueError) as exc:
        print(f"QR-code scan failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nQR-code scan cancelled.", file=sys.stderr)
        return 130

    print("No valid QR code was detected before timeout.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
