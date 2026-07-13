"""使用底盘低速左右转向，自动搜索并识别二维码。"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.algorithms.qr_detect import QRCodeRecognitionError, QRCodeRecognizer
from src.hardware.camera import CameraCaptureError, OpenCVCameraSession
from src.hardware.motor import MotorController
from src.tasks.qr_scan import QRCodeAutoScanner


def parse_args() -> argparse.Namespace:
    """解析自动扫码的摄像头和安全运动参数。"""

    parser = argparse.ArgumentParser(description="底盘自动左右扫视并识别 TYPE:ID 二维码。")
    parser.add_argument("--device", type=int, default=1, help="OpenCV 摄像头编号。")
    parser.add_argument("--width", type=int, default=640, help="请求图像宽度。")
    parser.add_argument("--height", type=int, default=480, help="请求图像高度。")
    parser.add_argument("--timeout", type=float, default=30.0, help="最长扫描秒数。")
    parser.add_argument("--speed", type=int, default=20, help="原地转向速度，最高 40。")
    parser.add_argument(
        "--turn-pulse-seconds",
        type=float,
        default=0.12,
        help="每次短时转向秒数，最高 0.5。",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=0.35,
        help="每次停车后等待画面稳定的秒数。",
    )
    parser.add_argument(
        "--scan-window-seconds",
        type=float,
        default=0.6,
        help="每个停车位置连续识别的秒数。",
    )
    parser.add_argument(
        "--sweep-half-steps",
        type=int,
        default=6,
        help="从中间扫到一侧的大致转向步数。",
    )
    parser.add_argument(
        "--debug-output-dir",
        type=Path,
        default=Path("captures") / "qr_debug",
        help="超时时保存诊断照片的目录。",
    )
    parser.add_argument(
        "--enable-motion",
        action="store_true",
        help="明确允许电机运动；缺少此参数时拒绝启动。",
    )
    return parser.parse_args()


def main() -> int:
    """运行自动扫视，成功时打印结构化二维码内容。"""

    args = parse_args()
    if not args.enable_motion:
        print(
            "安全拦截：本工具会让小车原地转向。请架空车轮短测，确认安全后加 "
            "--enable-motion。",
            file=sys.stderr,
        )
        return 2

    print("二维码自动扫描开始。", flush=True)
    print("预期格式: TYPE:ID，例如 TOLL:GATE1", flush=True)
    print(f"摄像头: device={args.device}, {args.width}x{args.height}", flush=True)
    print(
        f"运动参数: speed={args.speed}, pulse={args.turn_pulse_seconds}s, "
        f"settle={args.settle_seconds}s",
        flush=True,
    )

    motor = None
    try:
        recognizer = QRCodeRecognizer()
        motor = MotorController()
        with OpenCVCameraSession(
            device_index=args.device,
            width=args.width,
            height=args.height,
            warmup_frames=8,
            warmup_seconds=0.8,
        ) as camera:
            scanner = QRCodeAutoScanner(camera, motor, recognizer)
            result = scanner.scan(
                timeout_seconds=args.timeout,
                turn_speed=args.speed,
                turn_pulse_seconds=args.turn_pulse_seconds,
                settle_seconds=args.settle_seconds,
                scan_window_seconds=args.scan_window_seconds,
                sweep_half_steps=args.sweep_half_steps,
                progress_fn=lambda message: print(message, flush=True),
            )

            print(
                f"扫描统计: frames={result.frames_scanned}, "
                f"turns={result.turn_count}, elapsed={result.elapsed_seconds:.1f}s",
                flush=True,
            )
            for invalid_text in result.invalid_texts:
                print(f"识别到但格式无效: {invalid_text!r}", file=sys.stderr)

            if result.payload is not None:
                print("成功识别有效二维码。")
                print(f"Raw text: {result.payload.raw_text}")
                print(f"Type: {result.payload.qr_type}")
                print(f"Identifier: {result.payload.identifier}")
                return 0

            debug_path = _build_debug_path(args.debug_output_dir)
            capture = camera.capture(debug_path, burst_count=3)
            print("扫描超时，未识别到有效二维码。", file=sys.stderr)
            print(f"诊断照片已保存: {capture.path}", file=sys.stderr)
            print(f"诊断照片清晰度: {capture.sharpness:.2f}", file=sys.stderr)
            return 1
    except (CameraCaptureError, QRCodeRecognitionError, RuntimeError, ValueError) as exc:
        print(f"二维码自动扫描失败: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n用户取消扫描，小车已停车。", file=sys.stderr)
        return 130
    finally:
        if motor is not None:
            motor.close()


def _build_debug_path(output_dir: Path) -> Path:
    """生成本次超时诊断照片路径。

    参数：
        output_dir: 保存诊断照片的目录。
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"qr_timeout_{timestamp}.jpg"


if __name__ == "__main__":
    raise SystemExit(main())
