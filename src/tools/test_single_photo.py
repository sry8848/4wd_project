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
from contextlib import ExitStack
import multiprocessing
from pathlib import Path
import sys
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware.camera import (
    CameraCaptureError,
    OpenCVCameraSession,
    OpenCVCameraSettings,
    build_photo_path,
    capture_photo,
)
from src.hardware.servo import ServoError
from src.tasks.camera_servo_scan import CameraServoScanner
from src.tools.camera_servo_support import (
    add_camera_servo_arguments,
    enter_camera_servos,
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
        "--device-path",
        type=Path,
        help="舵机扫描时使用的稳定 V4L2 路径，例如 /dev/v4l/by-id/...。",
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
    parser.add_argument(
        "--device-timeout-seconds",
        type=float,
        default=12.0,
        help="每个摄像头编号最多等待多久；小于等于 0 表示不启用超时保护。",
    )
    parser.add_argument(
        "--servo-scan-timeout",
        type=float,
        default=60.0,
        help="转动摄像头并完成全部方向拍照的最长秒数。",
    )
    add_camera_servo_arguments(parser, default_frames_per_position=1)
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


def capture_device_with_timeout(
    args: argparse.Namespace,
    device_index: int,
    output_path: Path,
):
    """带超时保护地测试一个摄像头编号。

    参数:
        args: 已解析的命令行参数。
        device_index: OpenCV 摄像头编号。
        output_path: 本次测试照片保存路径。

    返回:
        CaptureResult。
    """

    kwargs = {
        "output_path": output_path,
        "backend": args.backend,
        "device_index": device_index,
        "width": args.width,
        "height": args.height,
        "warmup_frames": args.warmup_frames,
        "warmup_seconds": args.warmup_seconds,
        "settings": build_camera_settings(args),
        "burst_count": args.burst_count,
    }
    if args.device_timeout_seconds <= 0:
        return capture_photo(**kwargs)

    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=_capture_worker, args=(queue, kwargs))
    process.start()
    process.join(args.device_timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(1)
        raise CameraCaptureError(
            f"摄像头 {device_index} 超过 {args.device_timeout_seconds:.1f}s 没有返回，"
            "可能是设备节点不可采集或被占用"
        )

    if queue.empty():
        raise CameraCaptureError(f"摄像头 {device_index} 子进程没有返回结果")

    status, payload = queue.get()
    if status == "error":
        raise CameraCaptureError(payload)
    return payload


def _capture_worker(queue: multiprocessing.Queue, kwargs: dict) -> None:
    """在子进程里执行拍照，避免坏设备节点卡住主流程。"""

    try:
        queue.put(("ok", capture_photo(**kwargs)))
    except Exception as exc:  # noqa: BLE001 - worker must serialize all failures.
        queue.put(("error", str(exc)))


def _servo_photo_path(args, scan_frame) -> Path:
    """生成包含扫描序号和舵机角度的唯一照片路径。

    参数:
        args: 已解析的照片输出参数。
        scan_frame: 带有扫描位置和舵机角度的公共帧对象。
    """

    angle_suffix = (
        f"{scan_frame.position_index:03d}_pan_{scan_frame.pan_angle:g}_"
        f"tilt_{scan_frame.tilt_angle:g}"
    )
    if args.output is not None:
        suffix = args.output.suffix or ".jpg"
        return args.output.parent / f"{args.output.stem}_{angle_suffix}{suffix}"
    return build_photo_path(
        output_dir=args.output_dir,
        prefix=f"servo_photo_{angle_suffix}",
        extension=".jpg",
    )


def capture_servo_photo_scan(args: argparse.Namespace) -> int:
    """转动摄像头，并在每个扫描方向保存一张照片。

    参数:
        args: 摄像头、照片输出和公共舵机扫描参数。

    简单步骤:
    1. 在同一个 ExitStack 中打开 USB 摄像头和两个舵机。
    2. 每个位置读取设定数量的新画面，采用最后一帧。
    3. 保存每个方向的照片并输出实际路径。
    """

    if args.backend not in ("auto", "opencv"):
        raise ValueError("舵机扫描拍照只支持 OpenCV 摄像头后端")
    if args.servo_scan_timeout <= 0:
        raise ValueError("--servo-scan-timeout 必须大于 0")

    selected_device = (
        str(args.device_path) if args.device_path is not None else args.devices[0]
    )
    saved_photos = []

    with ExitStack() as stack:
        camera = stack.enter_context(
            OpenCVCameraSession(
                device_index=selected_device,
                width=args.width,
                height=args.height,
                warmup_frames=args.warmup_frames,
                warmup_seconds=args.warmup_seconds,
                settings=build_camera_settings(args),
            )
        )
        pan_servo, tilt_servo = enter_camera_servos(stack, args)

        def save_position_photo(scan_frame):
            if scan_frame.frame_index != args.frames_per_position:
                return None
            output_path = _servo_photo_path(args, scan_frame)
            diagnostics = camera.save_diagnostic_frame(output_path, scan_frame.frame)
            saved_photos.append(diagnostics)
            print(
                f"已保存位置 {scan_frame.position_index}: {diagnostics.path} "
                f"({diagnostics.width}x{diagnostics.height}, "
                f"pan={scan_frame.pan_angle:.1f}, tilt={scan_frame.tilt_angle:.1f})",
                flush=True,
            )
            return None

        result = CameraServoScanner(camera, pan_servo, tilt_servo).scan(
            save_position_photo,
            pan_angles=args.pan_angles,
            tilt_angles=args.tilt_angles,
            frames_per_position=args.frames_per_position,
            discard_frames_after_move=args.discard_frames,
            timeout_seconds=args.servo_scan_timeout,
            progress_fn=lambda message: print(message, flush=True),
        )

    expected_count = len(args.pan_angles) * len(args.tilt_angles)
    print(
        f"舵机扫描拍照保存 {len(saved_photos)}/{expected_count} 张，"
        f"耗时 {result.elapsed_seconds:.1f}s。",
        flush=True,
    )
    if result.timed_out or len(saved_photos) != expected_count:
        print("舵机扫描未能保存全部方向的照片。", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """执行普通拍照测试流程。

    简单步骤：
        1. 按顺序尝试摄像头编号。
        2. 每个编号拍一张照片并保存。
        3. 第一次成功后退出，失败时打印原因并继续尝试下一个编号。
    """

    args = parse_args()

    if args.enable_servo_motion:
        try:
            return capture_servo_photo_scan(args)
        except (CameraCaptureError, ServoError, ValueError) as exc:
            print(f"舵机扫描拍照失败: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\n用户取消舵机扫描拍照，硬件已释放。", file=sys.stderr)
            return 130

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
            result = capture_device_with_timeout(args, device_index, output_path)
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
