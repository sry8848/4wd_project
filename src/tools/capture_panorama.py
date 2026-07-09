"""Capture panorama photos with the camera pan servo.

Recommended first hardware check:

    python3 src/tools/capture_panorama.py --backend opencv --device 0 --frames 5 --no-stitch

After source photos look stable, run without ``--no-stitch`` to create the
final panorama image.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config
from src.hardware.camera import CameraCaptureError, OpenCVCameraSettings
from src.hardware.servo import ServoError
from src.tasks.panorama import (
    DEFAULT_PANORAMA_DIR,
    PanoramaError,
    capture_panorama,
    stitch_images,
)


def parse_optional_int(value: str):
    """Parse a GPIO pin number, or ``none`` for disabled optional pins."""

    if value.lower() in ("none", "off", "disabled"):
        return None
    return int(value)


def parse_optional_float(value: str):
    """Parse a float angle, or ``none`` for disabled optional angles."""

    if value.lower() in ("none", "off", "disabled"):
        return None
    return float(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture panorama source photos and optionally stitch them."
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "opencv", "libcamera", "raspistill"),
        default="auto",
        help="Camera backend. Use opencv for USB cameras.",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=0,
        help="OpenCV camera index. Ignored by libcamera/raspistill.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PANORAMA_DIR,
        help="Parent directory for timestamped panorama sessions.",
    )
    parser.add_argument(
        "--session-name",
        default=None,
        help="Optional exact session directory name.",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=config.PANORAMA_FRAME_COUNT,
        help="Number of source photos to capture.",
    )
    parser.add_argument(
        "--start-angle",
        type=float,
        default=config.PANORAMA_START_ANGLE,
        help="First horizontal pan angle, 0-180 degrees.",
    )
    parser.add_argument(
        "--end-angle",
        type=float,
        default=config.PANORAMA_END_ANGLE,
        help="Last horizontal pan angle, 0-180 degrees.",
    )
    parser.add_argument(
        "--pan-pin",
        type=parse_optional_int,
        default=config.CAMERA_PAN_SERVO_PIN,
        help="Horizontal pan servo BCM pin, or none.",
    )
    parser.add_argument(
        "--tilt-pin",
        type=parse_optional_int,
        default=config.CAMERA_TILT_SERVO_PIN,
        help="Optional vertical tilt servo BCM pin, or none.",
    )
    parser.add_argument(
        "--tilt-angle",
        type=parse_optional_float,
        default=config.PANORAMA_TILT_ANGLE,
        help="Optional vertical tilt angle before capture, or none.",
    )
    parser.add_argument(
        "--no-servo",
        action="store_true",
        help="Do not move servos; capture all frames from the current direction.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="Requested camera frame width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=960,
        help="Requested camera frame height.",
    )
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=5,
        help="Frames to discard before saving each photo.",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.5,
        help="Delay after opening the camera.",
    )
    parser.add_argument(
        "--servo-settle-seconds",
        type=float,
        default=0.5,
        help="Delay after each servo angle command.",
    )
    parser.add_argument(
        "--capture-delay-seconds",
        type=float,
        default=0.4,
        help="Extra delay before reading each frame.",
    )
    parser.add_argument("--fps", type=float, default=None, help="Requested camera frame rate.")
    parser.add_argument("--fourcc", default="MJPG", help="Requested format, for example MJPG or YUYV.")
    parser.add_argument("--brightness", type=float, default=None, help="Camera brightness if supported.")
    parser.add_argument("--contrast", type=float, default=None, help="Camera contrast if supported.")
    parser.add_argument("--saturation", type=float, default=None, help="Camera saturation if supported.")
    parser.add_argument("--gain", type=float, default=None, help="Camera gain if supported.")
    parser.add_argument("--exposure", type=float, default=None, help="Camera exposure if supported.")
    parser.add_argument("--focus", type=float, default=None, help="Camera focus if supported.")
    parser.add_argument("--sharpness", type=float, default=None, help="Camera-side sharpness if supported.")
    parser.add_argument(
        "--autofocus",
        choices=("on", "off", "keep"),
        default="keep",
        help="Autofocus control. Use off when setting --focus manually.",
    )
    parser.add_argument(
        "--auto-exposure",
        type=float,
        default=None,
        help="Raw OpenCV/V4L2 auto exposure value, often 1=manual and 3=auto.",
    )
    parser.add_argument(
        "--burst-count",
        type=int,
        default=1,
        help="Capture candidate frames and save the sharpest one at each angle.",
    )
    parser.add_argument(
        "--no-stitch",
        action="store_true",
        help="Only save source photos; skip OpenCV panorama stitching.",
    )
    parser.add_argument(
        "--stitch-confidence",
        type=float,
        default=0.01,
        help="OpenCV Stitcher confidence threshold.",
    )
    return parser.parse_args()


def build_camera_settings(args: argparse.Namespace) -> OpenCVCameraSettings:
    """Build OpenCV camera settings from command-line arguments."""

    autofocus = None
    if args.autofocus == "on":
        autofocus = True
    elif args.autofocus == "off":
        autofocus = False

    return OpenCVCameraSettings(
        fps=args.fps,
        fourcc=args.fourcc,
        brightness=args.brightness,
        contrast=args.contrast,
        saturation=args.saturation,
        gain=args.gain,
        exposure=args.exposure,
        focus=args.focus,
        sharpness=args.sharpness,
        autofocus=autofocus,
        auto_exposure=args.auto_exposure,
    )


def main() -> int:
    args = parse_args()

    print("Panorama capture started.", flush=True)
    print(f"Project root: {PROJECT_ROOT}", flush=True)
    print(f"Backend: {args.backend}", flush=True)
    print(f"Device index: {args.device}", flush=True)
    print(
        f"Angles: {args.start_angle} -> {args.end_angle}, frames: {args.frames}",
        flush=True,
    )
    if args.no_servo:
        print("Servo movement: disabled", flush=True)
    else:
        print(f"Pan servo BCM pin: {args.pan_pin}", flush=True)
        if args.tilt_pin is not None and args.tilt_angle is not None:
            print(
                f"Tilt servo BCM pin: {args.tilt_pin}, angle: {args.tilt_angle}",
                flush=True,
            )

    try:
        result = capture_panorama(
            output_dir=args.output_dir,
            session_name=args.session_name,
            backend=args.backend,
            device_index=args.device,
            width=args.width,
            height=args.height,
            warmup_frames=args.warmup_frames,
            warmup_seconds=args.warmup_seconds,
            start_angle=args.start_angle,
            end_angle=args.end_angle,
            frame_count=args.frames,
            pan_servo_pin=args.pan_pin,
            tilt_servo_pin=args.tilt_pin,
            tilt_angle=args.tilt_angle,
            use_servo=not args.no_servo,
            servo_settle_seconds=args.servo_settle_seconds,
            capture_delay_seconds=args.capture_delay_seconds,
            camera_settings=build_camera_settings(args),
            burst_count=args.burst_count,
            stitch=False,
        )
    except (CameraCaptureError, PanoramaError, ServoError, ValueError) as exc:
        print(f"Panorama capture failed: {exc}", file=sys.stderr)
        print(
            "Hint: first try fewer frames with --no-stitch, confirm --device 0/1, "
            "and make sure the car is stationary.",
            file=sys.stderr,
        )
        return 1

    print(f"Source frames saved: {len(result.frame_paths)}", flush=True)
    print(f"Session directory: {result.session_dir}", flush=True)

    if args.no_stitch:
        print("Stitching skipped.", flush=True)
        print("Panorama capture finished.", flush=True)
        return 0

    print("Stitching source frames...", flush=True)
    try:
        panorama_path = stitch_images(
            result.frame_paths,
            result.session_dir / "panorama.jpg",
            confidence_threshold=args.stitch_confidence,
        )
    except PanoramaError as exc:
        print(f"Panorama stitching failed: {exc}", file=sys.stderr)
        print(f"Source frames are kept in: {result.session_dir / 'frames'}")
        return 1

    print(f"Panorama saved: {panorama_path}", flush=True)
    print("Panorama capture finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
