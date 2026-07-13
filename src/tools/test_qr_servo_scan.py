"""使用摄像头上下、左右两个舵机自动搜索二维码。"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from pathlib import Path
import sys
from typing import Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config
from src.algorithms.qr_detect import QRCodeRecognitionError, QRCodeRecognizer
from src.hardware.camera import CameraCaptureError, OpenCVCameraSession
from src.hardware.servo import ServoController, ServoError
from src.tasks.qr_servo_scan import QRCodeServoScanner


def parse_angle_list(value: str) -> Tuple[float, ...]:
    """解析逗号分隔的安全测试角度。

    参数：
        value: 例如 ``90,70,110,50,130``。

    返回：
        保持输入顺序的浮点角度元组。
    """

    try:
        angles = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("角度必须是数字") from exc
    if not angles:
        raise argparse.ArgumentTypeError("至少需要一个角度")
    # 首次自动搜索保留机械余量，避免直接撞到 0/180 度极限。
    if any(angle < 20 or angle > 160 for angle in angles):
        raise argparse.ArgumentTypeError("自动搜索角度必须在 20 到 160 之间")
    return angles


def parse_args() -> argparse.Namespace:
    """解析摄像头、舵机扫描角度和超时参数。"""

    parser = argparse.ArgumentParser(description="双舵机云台自动搜索 TYPE:ID 二维码。")
    parser.add_argument(
        "--device",
        type=int,
        default=1,
        help="OpenCV 摄像头编号；当前普通拍照成功的编号为 1。",
    )
    parser.add_argument("--width", type=int, default=640, help="请求图像宽度。")
    parser.add_argument("--height", type=int, default=480, help="请求图像高度。")
    parser.add_argument(
        "--pan-pin",
        type=int,
        default=config.CAMERA_PAN_SERVO_PIN,
        help="左右舵机 BCM 引脚，已确认默认为 11/J2。",
    )
    parser.add_argument(
        "--tilt-pin",
        type=int,
        default=config.CAMERA_TILT_SERVO_PIN,
        help="上下舵机 BCM 引脚，已确认默认为 9/J3。",
    )
    parser.add_argument(
        "--pan-angles",
        type=parse_angle_list,
        default=parse_angle_list("90,70,110,50,130"),
        help="左右扫描角度，例如 90,70,110,50,130。",
    )
    parser.add_argument(
        "--tilt-angles",
        type=parse_angle_list,
        default=parse_angle_list("90,75,105"),
        help="上下扫描角度，例如 90,75,105。",
    )
    parser.add_argument(
        "--frames-per-position",
        type=int,
        default=10,
        help="每个云台位置连续识别的帧数。",
    )
    parser.add_argument(
        "--discard-frames",
        type=int,
        default=3,
        help="每次舵机移动后丢弃的摄像头缓冲帧数。",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="最长搜索秒数。")
    parser.add_argument(
        "--servo-settle-seconds",
        type=float,
        default=0.4,
        help="每次舵机动作后的稳定等待时间。",
    )
    parser.add_argument(
        "--enable-servo-motion",
        action="store_true",
        help="明确允许两个摄像头舵机运动；缺少时拒绝启动。",
    )
    return parser.parse_args()


def main() -> int:
    """执行双舵机搜索并在终端输出二维码及最终角度。"""

    args = parse_args()
    if not args.enable_servo_motion:
        print(
            "安全拦截：本工具会移动摄像头云台，请确认周围无遮挡后添加 "
            "--enable-servo-motion。",
            file=sys.stderr,
        )
        return 2
    if args.pan_pin == args.tilt_pin:
        print("左右和上下舵机不能使用同一个 BCM 引脚。", file=sys.stderr)
        return 2

    print("双舵机二维码搜索开始。", flush=True)
    print("预期格式: TYPE:ID，例如 TOLL:GATE1", flush=True)
    print(f"摄像头: device={args.device}, {args.width}x{args.height}", flush=True)
    print(f"左右舵机: BCM {args.pan_pin}, angles={args.pan_angles}", flush=True)
    print(f"上下舵机: BCM {args.tilt_pin}, angles={args.tilt_angles}", flush=True)

    try:
        recognizer = QRCodeRecognizer()
        # ExitStack 统一拥有并释放摄像头和两个舵机，异常与 Ctrl+C 也会执行。
        with ExitStack() as stack:
            camera = stack.enter_context(
                OpenCVCameraSession(
                    device_index=args.device,
                    width=args.width,
                    height=args.height,
                    warmup_frames=8,
                    warmup_seconds=0.8,
                )
            )
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

            scanner = QRCodeServoScanner(
                camera,
                pan_servo,
                tilt_servo,
                recognizer,
            )
            result = scanner.scan(
                pan_angles=args.pan_angles,
                tilt_angles=args.tilt_angles,
                frames_per_position=args.frames_per_position,
                discard_frames_after_move=args.discard_frames,
                timeout_seconds=args.timeout,
                progress_fn=lambda message: print(message, flush=True),
            )

            print(
                f"扫描统计: positions={result.positions_scanned}, "
                f"frames={result.frames_scanned}, "
                f"elapsed={result.elapsed_seconds:.1f}s",
                flush=True,
            )
            for invalid_text in result.invalid_texts:
                print(f"识别到但格式无效: {invalid_text!r}", file=sys.stderr)

            if result.payload is None:
                print("扫描结束，未识别到有效二维码。", file=sys.stderr)
                return 1

            print("成功识别有效二维码。")
            print(f"Raw text: {result.payload.raw_text}")
            print(f"Type: {result.payload.qr_type}")
            print(f"Identifier: {result.payload.identifier}")
            print(f"Pan angle: {result.pan_angle:.1f}")
            print(f"Tilt angle: {result.tilt_angle:.1f}")
            return 0
    except (CameraCaptureError, QRCodeRecognitionError, ServoError, ValueError) as exc:
        print(f"双舵机二维码搜索失败: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n用户取消搜索，摄像头和舵机资源已释放。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
