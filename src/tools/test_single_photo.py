"""普通拍照测试脚本。

用途：
    在树莓派上快速验证摄像头能否打开、能否保存一张照片。

常用命令：
    python3 src/tools/test_single_photo.py
    python3 src/tools/test_single_photo.py --devices 1 --backend opencv
    python3 src/tools/test_single_photo.py --output captures/test.jpg
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware.camera import (
    CameraCaptureError,
    OpenCVCameraSettings,
    build_photo_path,
    capture_photo,
)


def parse_devices(value: str) -> List[int]:
    """解析命令行传入的摄像头编号列表。

    参数：
        value: 逗号分隔的摄像头编号，例如 ``0,1,2``。

    返回：
        摄像头编号列表。
    """

    devices = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        devices.append(int(item))
    if not devices:
        raise argparse.ArgumentTypeError("至少需要一个摄像头编号")
    return devices


def parse_args() -> argparse.Namespace:
    """解析普通拍照测试参数。"""

    parser = argparse.ArgumentParser(description="普通摄像头拍照测试。")
    parser.add_argument(
        "--backend",
        choices=("auto", "opencv", "libcamera", "raspistill"),
        default="auto",
        help="拍照后端。USB 摄像头优先试 opencv；CSI 摄像头可试 libcamera 或 raspistill。",
    )
    parser.add_argument(
        "--devices",
        type=parse_devices,
        default=parse_devices("0,1"),
        help="要尝试的 OpenCV 摄像头编号，多个编号用逗号分隔，例如 0,1。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="指定输出照片路径。只测试一个摄像头时推荐使用。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("captures"),
        help="未指定 --output 时，照片保存到这个目录。",
    )
    parser.add_argument("--width", type=int, default=None, help="请求图像宽度。")
    parser.add_argument("--height", type=int, default=None, help="请求图像高度。")
    parser.add_argument("--fps", type=float, default=None, help="请求帧率。")
    parser.add_argument("--fourcc", default="MJPG", help="请求图像格式，例如 MJPG 或 YUYV。")
    parser.add_argument("--brightness", type=float, default=None, help="亮度值，需要摄像头支持。")
    parser.add_argument("--contrast", type=float, default=None, help="对比度值，需要摄像头支持。")
    parser.add_argument("--saturation", type=float, default=None, help="饱和度值，需要摄像头支持。")
    parser.add_argument("--gain", type=float, default=None, help="增益值，需要摄像头支持。")
    parser.add_argument("--exposure", type=float, default=None, help="曝光值，需要摄像头支持。")
    parser.add_argument("--focus", type=float, default=None, help="焦距值，需要摄像头支持。")
    parser.add_argument("--sharpness", type=float, default=None, help="摄像头端锐化值，需要驱动支持。")
    parser.add_argument(
        "--autofocus",
        choices=("on", "off", "keep"),
        default="keep",
        help="自动对焦控制。手动设置 --focus 时建议 off。",
    )
    parser.add_argument(
        "--auto-exposure",
        type=float,
        default=None,
        help="OpenCV/V4L2 自动曝光原始值，常见 1=manual, 3=auto。",
    )
    parser.add_argument(
        "--burst-count",
        type=int,
        default=1,
        help="连拍张数，自动保存清晰度分数最高的一张。",
    )
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=8,
        help="正式保存前丢弃的预热帧数。",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.8,
        help="打开摄像头后的预热时间。",
    )
    return parser.parse_args()


def build_camera_settings(args: argparse.Namespace) -> OpenCVCameraSettings:
    """根据命令行参数构造 OpenCV 摄像头控制项。

    参数:
        args: 已解析的命令行参数。

    返回:
        OpenCVCameraSettings，供底层摄像头模块统一应用。
    """

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
    """执行普通拍照测试流程。

    简单步骤：
        1. 按顺序尝试摄像头编号。
        2. 每个编号拍一张照片并保存。
        3. 第一次成功后退出，失败时打印原因并继续尝试下一个编号。
    """

    args = parse_args()

    print("普通拍照测试开始。", flush=True)
    print(f"项目目录: {PROJECT_ROOT}", flush=True)
    print(f"拍照后端: {args.backend}", flush=True)
    print(f"尝试摄像头编号: {args.devices}", flush=True)

    errors = []
    for device_index in args.devices:
        output_path = args.output
        if output_path is None:
            output_path = build_photo_path(
                output_dir=args.output_dir,
                prefix=f"single_photo_device_{device_index}",
                extension=".jpg",
            )

        print(f"正在尝试摄像头 {device_index}...", flush=True)
        try:
            result = capture_photo(
                output_path=output_path,
                backend=args.backend,
                device_index=device_index,
                width=args.width,
                height=args.height,
                warmup_frames=args.warmup_frames,
                warmup_seconds=args.warmup_seconds,
                settings=build_camera_settings(args),
                burst_count=args.burst_count,
            )
        except CameraCaptureError as exc:
            message = f"摄像头 {device_index} 拍照失败: {exc}"
            errors.append(message)
            print(message, file=sys.stderr)
            continue

        print("普通拍照测试成功。", flush=True)
        print(f"照片路径: {result.path}", flush=True)
        print(f"实际后端: {result.backend}", flush=True)
        if result.device_index is not None:
            print(f"摄像头编号: {result.device_index}", flush=True)
        if result.width and result.height:
            print(f"图像分辨率: {result.width}x{result.height}", flush=True)
        if result.sharpness is not None:
            print(f"清晰度分数: {result.sharpness:.2f}", flush=True)
        return 0

    print("所有摄像头编号都拍照失败。", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    print("建议：先确认摄像头排线/USB连接，再尝试 --backend opencv --devices 1。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
