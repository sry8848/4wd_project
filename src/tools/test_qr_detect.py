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
from src import config as project_config
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
        default=project_config.TOLL_QR_TIMEOUT_SECONDS,
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
        help="Directory used for timestamped diagnostic JPEGs.",
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
        frame: Frame selected for diagnostic output.
        output_dir: Destination directory for the timestamped JPEG.
        prefix: Prefix identifying timeout, runtime-error, or success output.

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


def print_diagnostic_summary(
    *,
    result: str,
    started_at: float,
    frames_read: int,
    corner_frames: int,
    decoded_frames: int,
    invalid_payloads: int,
) -> None:
    """Print one compact, AI-readable summary for the completed scan.

    Args:
        result: Stable result label such as ``success`` or ``timeout``.
        started_at: Monotonic start time for elapsed-time calculation.
        frames_read: Number of frames successfully returned by the camera.
        corner_frames: Frames where OpenCV returned QR corner coordinates.
        decoded_frames: Frames where at least one QR text was decoded.
        invalid_payloads: Number of unique decoded texts rejected by TYPE:ID.
    """

    print(
        "DIAG summary "
        f"result={result} "
        f"frames_read={frames_read} "
        f"corner_frames={corner_frames} "
        f"decoded_frames={decoded_frames} "
        f"invalid_payloads={invalid_payloads} "
        f"elapsed_seconds={time.monotonic() - started_at:.1f}",
        flush=True,
    )


def main() -> int:
    """Scan until one valid project QR code is read or timeout expires."""

    args = parse_args()
    if args.timeout <= 0:
        print("--timeout must be greater than 0", file=sys.stderr)
        return 2
    if args.progress_interval <= 0:
        print("--progress-interval must be greater than 0", file=sys.stderr)
        return 2

    if args.device_path is not None:
        if not args.device_path.exists():
            print(f"--device-path does not exist: {args.device_path}", file=sys.stderr)
            return 2
        if not args.device_path.is_char_device():
            print(
                "--device-path must point to a V4L2 character device, "
                f"got: {args.device_path}",
                file=sys.stderr,
            )
            return 2

    print("QR-code scan started.", flush=True)
    print("Expected format: TYPE:ID (example: TOLL:GATE1)", flush=True)
    selected_device = (
        str(args.device_path) if args.device_path is not None else args.device
    )
    print(f"Camera: device={selected_device}, {args.width}x{args.height}", flush=True)
    print(f"Timeout: {args.timeout:.1f} seconds", flush=True)

    resolved_device = (
        str(args.device_path.resolve())
        if args.device_path is not None
        else f"opencv-index:{args.device}"
    )
    print(
        f"DIAG device input={selected_device} resolved={resolved_device}",
        flush=True,
    )

    started_at = time.monotonic()
    deadline = started_at + args.timeout
    next_progress_at = started_at + args.progress_interval
    reported_invalid_texts = set()
    frames_read = 0
    corner_frames = 0
    decoded_frames = 0
    latest_frame = None
    detected_frame = None
    camera = None

    try:
        recognizer = QRCodeRecognizer()
        import cv2

        print(
            f"DIAG decoder backend=opencv_qrcode version={cv2.__version__}",
            flush=True,
        )
        camera = OpenCVCameraSession(
            device_index=selected_device,
            width=args.width,
            height=args.height,
            warmup_frames=5,
            warmup_seconds=args.warmup_seconds,
        )
        camera.open()

        while time.monotonic() < deadline:
            # 1. Read the latest camera frame.
            frame = camera.read_frame()
            frames_read += 1
            latest_frame = frame
            if frames_read == 1:
                height, width = frame.shape[:2]
                channels = frame.shape[2] if len(frame.shape) >= 3 else 1
                print(
                    f"DIAG frame width={width} height={height} "
                    f"channels={channels}",
                    flush=True,
                )

            # 2. Decode every QR code visible in this frame.
            decode_result = recognizer.decode_with_diagnostics(frame)
            if decode_result.corners_detected:
                corner_frames += 1
                if detected_frame is None:
                    detected_frame = frame.copy()
            if decode_result.texts:
                decoded_frames += 1

            for raw_text in decode_result.texts:
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

                # 3. Stop after the first valid result.
                print_diagnostic_summary(
                    result="success",
                    started_at=started_at,
                    frames_read=frames_read,
                    corner_frames=corner_frames,
                    decoded_frames=decoded_frames,
                    invalid_payloads=len(reported_invalid_texts),
                )
                print("Valid QR code detected.")
                print(f"Raw text: {payload.raw_text}")
                print(f"Type: {payload.qr_type}")
                print(f"Identifier: {payload.identifier}")
                if args.save_success_photo:
                    save_and_report_snapshot(
                        camera,
                        latest_frame,
                        args.diagnostic_dir,
                        "qr_success",
                    )
                return 0

            now = time.monotonic()
            if now >= next_progress_at:
                print(
                    "DIAG progress "
                    f"frames_read={frames_read} "
                    f"corner_frames={corner_frames} "
                    f"decoded_frames={decoded_frames}",
                    flush=True,
                )
                next_progress_at = now + args.progress_interval

        print_diagnostic_summary(
            result="timeout",
            started_at=started_at,
            frames_read=frames_read,
            corner_frames=corner_frames,
            decoded_frames=decoded_frames,
            invalid_payloads=len(reported_invalid_texts),
        )
        diagnostic_frame = (
            detected_frame if detected_frame is not None else latest_frame
        )
        save_and_report_snapshot(
            camera,
            diagnostic_frame,
            args.diagnostic_dir,
            "qr_timeout",
        )
        if corner_frames == 0:
            print("DIAG diagnosis=no_qr_corners", flush=True)
        elif decoded_frames == 0:
            print("DIAG diagnosis=corners_detected_but_not_decoded", flush=True)
        else:
            print("DIAG diagnosis=decoded_payload_invalid", flush=True)
        print("No valid QR code was detected before timeout.", file=sys.stderr)
        return 1

    except (CameraCaptureError, QRCodeRecognitionError, ValueError) as exc:
        print_diagnostic_summary(
            result="runtime_error",
            started_at=started_at,
            frames_read=frames_read,
            corner_frames=corner_frames,
            decoded_frames=decoded_frames,
            invalid_payloads=len(reported_invalid_texts),
        )
        if camera is not None:
            diagnostic_frame = (
                detected_frame if detected_frame is not None else latest_frame
            )
            save_and_report_snapshot(
                camera,
                diagnostic_frame,
                args.diagnostic_dir,
                "qr_runtime_error",
            )
        print(f"QR-code scan failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print_diagnostic_summary(
            result="cancelled",
            started_at=started_at,
            frames_read=frames_read,
            corner_frames=corner_frames,
            decoded_frames=decoded_frames,
            invalid_payloads=len(reported_invalid_texts),
        )
        print("\nQR-code scan cancelled.", file=sys.stderr)
        return 130
    finally:
        if camera is not None:
            camera.close()


if __name__ == "__main__":
    raise SystemExit(main())
