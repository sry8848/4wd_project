"""车身旋转 180 度全景拍照测试脚本。

用途：
    摄像头没有独立水平云台时，让小车原地旋转 180 度，每转一小段停下拍照。
    这是当前 Yahboom 4WD 小车更合适的 180 度全景测试方式。

常用命令：
    python3 src/tools/test_panorama_180_car_turn.py
    python3 src/tools/test_panorama_180_car_turn.py --frames 7 --speed 30 --total-turn-seconds 2.4
    python3 src/tools/test_panorama_180_car_turn.py --frames 13 --stitch
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware.camera import (
    CameraCaptureError,
    OpenCVCameraSettings,
    apply_opencv_camera_settings,
    sharpness_score,
)
from src.hardware.motor import MotorController
from src.tasks.panorama import PanoramaError, stitch_images


def parse_args() -> argparse.Namespace:
    """解析车身旋转全景拍照测试参数。"""

    parser = argparse.ArgumentParser(description="车身旋转 180 度全景拍照测试。")
    parser.add_argument(
        "--device",
        type=int,
        default=1,
        help="OpenCV 摄像头编号。你当前普通拍照测试成功的是 1。",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=7,
        help="拍照张数。第一次建议 7，稳定后可改 13。",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=30,
        help="原地旋转速度，范围 1 到 60。第一次不要太快。",
    )
    parser.add_argument(
        "--total-turn-seconds",
        type=float,
        default=2.4,
        help="预计完成 180 度旋转的总时长，需要按实机校准。",
    )
    parser.add_argument(
        "--direction",
        choices=("left", "right"),
        default="right",
        help="原地旋转方向。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("captures") / "panorama_180_car_turn_tests",
        help="测试照片输出目录。",
    )
    parser.add_argument("--width", type=int, default=640, help="请求图像宽度。")
    parser.add_argument("--height", type=int, default=480, help="请求图像高度。")
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
        "--warmup-frames",
        type=int,
        default=8,
        help="打开摄像头后丢弃的预热帧数。",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.8,
        help="打开摄像头后的预热时间。",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1.2,
        help="每次停车后等待车身稳定再拍照的时间。",
    )
    parser.add_argument(
        "--capture-retries",
        type=int,
        default=3,
        help="每张照片失败后的重试次数，用于处理 USB 摄像头短暂掉线。",
    )
    parser.add_argument(
        "--burst-count",
        type=int,
        default=3,
        help="每个角度连拍张数，自动保存最清晰的一张。",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=1.0,
        help="拍照失败后再次打开摄像头前的等待时间。",
    )
    parser.add_argument(
        "--stitch",
        action="store_true",
        help="拍完后尝试生成 panorama.jpg。",
    )
    return parser.parse_args()


def build_camera_settings(args: argparse.Namespace) -> OpenCVCameraSettings:
    """根据命令行参数构造 OpenCV 摄像头控制项。

    参数:
        args: 已解析的命令行参数。

    返回:
        OpenCVCameraSettings，供每次重新打开摄像头后应用。
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
    """执行车身旋转 180 度全景拍照测试。

    简单步骤：
        1. 先拍第 1 张照片，作为 0 度方向。
        2. 小车原地旋转一小段，停车等待稳定。
        3. 重复拍照，直到完成指定张数。
        4. 可选使用 OpenCV Stitcher 拼接全景图。
    """

    args = parse_args()
    _validate_args(args)

    session_dir = args.output_dir / datetime.now().strftime("car_turn_%Y%m%d_%H%M%S")
    frames_dir = session_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    turn_steps = max(1, args.frames - 1)
    step_seconds = args.total_turn_seconds / turn_steps

    print("车身旋转 180 度全景拍照测试开始。", flush=True)
    print(f"项目目录: {PROJECT_ROOT}", flush=True)
    print(f"摄像头编号: {args.device}", flush=True)
    print(f"拍照张数: {args.frames}", flush=True)
    print(f"旋转方向: {args.direction}", flush=True)
    print(f"旋转速度: {args.speed}", flush=True)
    print(f"180 度总旋转时长: {args.total_turn_seconds}s", flush=True)
    print(f"每次旋转时长: {step_seconds:.3f}s", flush=True)
    print(f"输出目录: {session_dir}", flush=True)

    motor = None
    frame_paths = []
    try:
        motor = MotorController()
        for index in range(args.frames):
            if index > 0:
                _spin_one_step(motor, args.direction, args.speed, step_seconds)
                time.sleep(args.settle_seconds)

            approx_angle = 180 * index / turn_steps
            frame_path = frames_dir / f"frame_{index:02d}_approx_{approx_angle:06.2f}.jpg"
            print(f"拍摄第 {index + 1}/{args.frames} 张，约 {approx_angle:.1f} 度...", flush=True)
            _capture_frame_with_retries(
                frame_path=frame_path,
                device_index=args.device,
                width=args.width,
                height=args.height,
                warmup_frames=args.warmup_frames,
                warmup_seconds=args.warmup_seconds,
                retries=args.capture_retries,
                retry_delay_seconds=args.retry_delay_seconds,
                burst_count=args.burst_count,
                settings=build_camera_settings(args),
            )
            frame_paths.append(frame_path)
    except (CameraCaptureError, RuntimeError, ValueError) as exc:
        print(f"车身旋转全景拍照失败: {exc}", file=sys.stderr)
        print("建议：先架空车轮短测 spin-right，再落地用较小速度和时长测试。", file=sys.stderr)
        return 1
    finally:
        if motor is not None:
            motor.close()

    panorama_path = None
    if args.stitch:
        try:
            panorama_path = stitch_images(frame_paths, session_dir / "panorama.jpg")
        except PanoramaError as exc:
            print(f"拼接失败: {exc}", file=sys.stderr)
            print(f"原始照片仍保留在: {frames_dir}", flush=True)
            return 1

    print("车身旋转 180 度全景拍照测试成功。", flush=True)
    print(f"原始照片目录: {frames_dir}", flush=True)
    for path in frame_paths:
        print(f"  {path}", flush=True)
    if panorama_path is not None:
        print(f"拼接结果: {panorama_path}", flush=True)
    return 0


def _spin_one_step(
    motor: MotorController,
    direction: str,
    speed: int,
    duration: float,
) -> None:
    """原地旋转一小段并立即停车。

    参数：
        motor: 已初始化的 MotorController。
        direction: ``left`` 或 ``right``。
        speed: PWM 速度。
        duration: 本次旋转持续时间。
    """

    if direction == "left":
        motor.spin_left(speed, speed)
    else:
        motor.spin_right(speed, speed)
    time.sleep(duration)
    motor.brake()


def _validate_args(args: argparse.Namespace) -> None:
    """限制危险参数，避免测试时小车长时间运动。"""

    if args.frames < 2:
        raise ValueError("frames 必须至少为 2")
    if args.speed < 1 or args.speed > 60:
        raise ValueError("speed 必须在 1 到 60 之间")
    if args.total_turn_seconds <= 0 or args.total_turn_seconds > 8:
        raise ValueError("total-turn-seconds 必须大于 0 且不超过 8 秒")
    if args.settle_seconds < 0:
        raise ValueError("settle-seconds 不能小于 0")
    if args.capture_retries < 0:
        raise ValueError("capture-retries 不能小于 0")
    if args.burst_count < 1:
        raise ValueError("burst-count 必须至少为 1")
    if args.retry_delay_seconds < 0:
        raise ValueError("retry-delay-seconds 不能小于 0")


def _capture_frame_with_retries(
    *,
    frame_path: Path,
    device_index: int,
    width: int,
    height: int,
    warmup_frames: int,
    warmup_seconds: float,
    retries: int,
    retry_delay_seconds: float,
    burst_count: int,
    settings: OpenCVCameraSettings,
) -> None:
    """打开摄像头连拍并保存最清晰的一张，失败时关闭并重试。

    参数：
        frame_path: 当前照片保存路径。
        device_index: OpenCV 摄像头编号。
        width: 请求图像宽度。
        height: 请求图像高度。
        warmup_frames: 正式保存前丢弃的预热帧数。
        warmup_seconds: 打开摄像头后的预热时间。
        retries: 失败后额外重试次数。
        retry_delay_seconds: 每次重试前等待时间。
        burst_count: 连拍张数。
    """

    try:
        import cv2
    except ImportError as exc:
        raise CameraCaptureError("OpenCV 未安装，无法拍照") from exc

    last_error = None
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            score = _capture_best_burst_frame(
                cv2=cv2,
                frame_path=frame_path,
                device_index=device_index,
                width=width,
                height=height,
                warmup_frames=warmup_frames,
                warmup_seconds=warmup_seconds,
                burst_count=burst_count,
                settings=settings,
            )
            print(f"  已保存最清晰帧，sharpness={score:.2f}", flush=True)
            return
        except CameraCaptureError as exc:
            last_error = exc
            print(f"  第 {attempt}/{attempts} 次拍照失败: {exc}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(retry_delay_seconds)

    raise CameraCaptureError(f"多次重试后仍无法拍照: {last_error}")


def _capture_best_burst_frame(
    *,
    cv2,
    frame_path: Path,
    device_index: int,
    width: int,
    height: int,
    warmup_frames: int,
    warmup_seconds: float,
    burst_count: int,
    settings: OpenCVCameraSettings,
) -> float:
    """从一次摄像头会话里连拍多帧，保存清晰度最高的一帧。

    参数：
        cv2: 已导入的 OpenCV 模块。
        frame_path: 最佳帧保存路径。
        device_index: OpenCV 摄像头编号。
        width: 请求图像宽度。
        height: 请求图像高度。
        warmup_frames: 预热帧数。
        warmup_seconds: 打开摄像头后的等待时间。
        burst_count: 参与挑选的帧数。

    返回：
        最佳帧的清晰度分数。
    """

    camera = cv2.VideoCapture(device_index)
    try:
        if not camera.isOpened():
            raise CameraCaptureError(f"Cannot open camera device {device_index}")

        camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        apply_opencv_camera_settings(cv2, camera, settings)
        if warmup_seconds > 0:
            time.sleep(warmup_seconds)

        best_frame = None
        best_score = -1.0
        total_reads = max(1, warmup_frames) + burst_count
        for read_index in range(total_reads):
            ok, frame = camera.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            if read_index < warmup_frames:
                continue
            score = sharpness_score(cv2, frame)
            if score > best_score:
                best_score = score
                best_frame = frame

        if best_frame is None:
            raise CameraCaptureError(f"Camera device {device_index} opened, but no frame was read.")
        if not cv2.imwrite(str(frame_path), best_frame):
            raise CameraCaptureError(f"Failed to write photo to {frame_path}")
        return best_score
    finally:
        camera.release()

if __name__ == "__main__":
    raise SystemExit(main())
