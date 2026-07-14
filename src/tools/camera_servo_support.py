"""Shared CLI options and hardware construction for camera-servo tools."""

from __future__ import annotations

import argparse
from typing import Tuple

from src import config
from src.hardware.servo import ServoController


DEFAULT_PAN_ANGLES = (90.0, 70.0, 110.0, 50.0, 130.0)
DEFAULT_TILT_ANGLES = (90.0, 75.0, 105.0)


def parse_angle_list(value: str) -> Tuple[float, ...]:
    """Parse comma-separated safe camera-servo angles.

    Args:
        value: Comma-separated numbers such as ``90,70,110``.
    """

    try:
        angles = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("角度必须是数字") from exc
    if not angles:
        raise argparse.ArgumentTypeError("至少需要一个角度")
    if any(angle < 20 or angle > 160 for angle in angles):
        raise argparse.ArgumentTypeError("自动搜索角度必须在 20 到 160 之间")
    return angles


def add_camera_servo_arguments(parser, *, default_frames_per_position: int = 10) -> None:
    """Add the same two-axis scan options to one command-line parser."""

    parser.add_argument(
        "--pan-pin",
        type=int,
        default=config.CAMERA_PAN_SERVO_PIN,
        help="左右舵机 BCM 引脚，默认为 11/J2。",
    )
    parser.add_argument(
        "--tilt-pin",
        type=int,
        default=config.CAMERA_TILT_SERVO_PIN,
        help="上下舵机 BCM 引脚，默认为 9/J3。",
    )
    parser.add_argument(
        "--pan-angles",
        type=parse_angle_list,
        default=DEFAULT_PAN_ANGLES,
        help="左右扫描角度，例如 90,70,110,50,130。",
    )
    parser.add_argument(
        "--tilt-angles",
        type=parse_angle_list,
        default=DEFAULT_TILT_ANGLES,
        help="上下扫描角度，例如 90,75,105。",
    )
    parser.add_argument(
        "--frames-per-position",
        type=int,
        default=default_frames_per_position,
        help="每个云台位置处理的画面帧数。",
    )
    parser.add_argument(
        "--discard-frames",
        type=int,
        default=3,
        help="每次舵机移动后丢弃的摄像头缓冲帧数。",
    )
    parser.add_argument(
        "--servo-settle-seconds",
        type=float,
        default=0.4,
        help="每次舵机动作后的稳定等待时间。",
    )
    parser.add_argument(
        "--enable-servo-motion",
        action="store_true",
        help="明确允许摄像头上下、左右舵机运动。",
    )


def enter_camera_servos(stack, args):
    """Create both camera servos under an ExitStack hardware owner.

    Args:
        stack: Outer ExitStack that owns camera and both servos.
        args: Parsed namespace containing shared servo settings.

    Steps:
    1. Reject a conflicting pin assignment before GPIO initialization.
    2. Enter the pan and tilt controllers under the caller's ExitStack.
    3. Return both controllers for CameraServoScanner.
    """

    if not args.enable_servo_motion:
        raise ValueError(
            "camera servo motion requires the explicit --enable-servo-motion flag"
        )
    if args.pan_pin == args.tilt_pin:
        raise ValueError("左右和上下舵机不能使用同一个 BCM 引脚")
    pan_servo = stack.enter_context(
        ServoController(
            args.pan_pin,
            settle_seconds=args.servo_settle_seconds,
        )
    )
    tilt_servo = stack.enter_context(
        ServoController(
            args.tilt_pin,
            settle_seconds=args.servo_settle_seconds,
        )
    )
    return pan_servo, tilt_servo
