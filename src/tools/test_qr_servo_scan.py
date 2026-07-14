"""使用摄像头上下、左右两个舵机自动搜索二维码。"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.algorithms.qr_detect import QRCodeRecognitionError, QRCodeRecognizer
from src.hardware.camera import CameraCaptureError, OpenCVCameraSession
from src.hardware.servo import ServoError
from src.tasks.qr_servo_scan import QRCodeServoScanner
from src.tools.camera_servo_support import (
    add_camera_servo_arguments,
    enter_camera_servos,
)
from src.tools.qr_scan_diagnostics import (
    DEFAULT_QR_DIAGNOSTIC_DIR,
    format_qr_snapshot_diagnostics,
    save_qr_diagnostic_snapshot,
)


def parse_args() -> argparse.Namespace:
    """解析摄像头、舵机扫描角度和超时参数。"""

    parser = argparse.ArgumentParser(description="双舵机云台自动搜索 TYPE:ID 二维码。")
    camera_source = parser.add_mutually_exclusive_group()
    camera_source.add_argument(
        "--device",
        type=int,
        default=0,
        help="OpenCV 摄像头编号，默认与后端一致使用 0。",
    )
    camera_source.add_argument(
        "--device-path",
        type=Path,
        help="稳定 V4L2 路径，例如 /dev/v4l/by-id/...-video-index0。",
    )
    parser.add_argument("--width", type=int, default=640, help="请求图像宽度。")
    parser.add_argument("--height", type=int, default=480, help="请求图像高度。")
    parser.add_argument("--timeout", type=float, default=30.0, help="最长搜索秒数。")
    add_camera_servo_arguments(parser, default_frames_per_position=10)
    parser.add_argument(
        "--diagnostic-dir",
        type=Path,
        default=DEFAULT_QR_DIAGNOSTIC_DIR,
        help="超时或成功诊断照片的保存目录。",
    )
    parser.add_argument(
        "--save-success-photo",
        action="store_true",
        help="识别成功时也保存对应画面，便于留存验收证据。",
    )
    return parser.parse_args()


def save_and_report_snapshot(camera, frame, output_dir, prefix) -> None:
    """保存最后识别画面并输出路径、亮度和清晰度。

    参数：
        camera: 当前打开的 OpenCVCameraSession。
        frame: 最后送入二维码识别器的画面。
        output_dir: 诊断图片目录。
        prefix: 区分超时或成功图片的文件名前缀。

    分步逻辑：
    1. 没有读取到画面时输出明确提示。
    2. 保存画面并打印图像质量指标。
    3. 保存失败只报告诊断错误，不覆盖原扫码结果。
    """

    try:
        result = save_qr_diagnostic_snapshot(
            camera,
            frame,
            output_dir=output_dir,
            prefix=prefix,
        )
    except CameraCaptureError as exc:
        print(f"诊断画面保存失败: {exc}", file=sys.stderr)
        return
    if result is None:
        print("扫码期间没有取得任何画面，无法保存诊断照片。", file=sys.stderr)
        return
    print(f"诊断画面: {format_qr_snapshot_diagnostics(result)}", flush=True)


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
    selected_device = (
        str(args.device_path) if args.device_path is not None else args.device
    )
    print("双舵机二维码搜索开始。", flush=True)
    print("预期格式: TYPE:ID，例如 TOLL:GATE1", flush=True)
    print(f"摄像头: device={selected_device}, {args.width}x{args.height}", flush=True)
    print(f"左右舵机: BCM {args.pan_pin}, angles={args.pan_angles}", flush=True)
    print(f"上下舵机: BCM {args.tilt_pin}, angles={args.tilt_angles}", flush=True)

    try:
        recognizer = QRCodeRecognizer()
        # ExitStack 统一拥有并释放摄像头和两个舵机，异常与 Ctrl+C 也会执行。
        with ExitStack() as stack:
            camera = stack.enter_context(
                OpenCVCameraSession(
                    device_index=selected_device,
                    width=args.width,
                    height=args.height,
                    warmup_frames=8,
                    warmup_seconds=0.8,
                )
            )
            pan_servo, tilt_servo = enter_camera_servos(stack, args)

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
                save_and_report_snapshot(
                    camera,
                    result.last_frame,
                    args.diagnostic_dir,
                    "qr_servo_timeout",
                )
                print("扫描结束，未识别到有效二维码。", file=sys.stderr)
                return 1

            print("成功识别有效二维码。")
            print(f"Raw text: {result.payload.raw_text}")
            print(f"Type: {result.payload.qr_type}")
            print(f"Identifier: {result.payload.identifier}")
            print(f"Pan angle: {result.pan_angle:.1f}")
            print(f"Tilt angle: {result.tilt_angle:.1f}")
            if args.save_success_photo:
                save_and_report_snapshot(
                    camera,
                    result.last_frame,
                    args.diagnostic_dir,
                    "qr_servo_success",
                )
            return 0
    except (CameraCaptureError, QRCodeRecognitionError, ServoError, ValueError) as exc:
        print(f"双舵机二维码搜索失败: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n用户取消搜索，摄像头和舵机资源已释放。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
