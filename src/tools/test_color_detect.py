"""Manual color-recognition tool for an image file or the car camera.

Examples:
    python3 src/tools/test_color_detect.py --image captures/photo.jpg
    python3 src/tools/test_color_detect.py --device 1 --timeout 15
    python3 src/tools/test_color_detect.py \
        --device-path /dev/v4l/by-id/...-video-index0 --timeout 15
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.algorithms.color_detect import (
    DEFAULT_COLOR_SPECS,
    ColorDetectionError,
    ColorDetectionResult,
    ColorDetector,
)
from src import config as project_config
from src.hardware.camera import CameraCaptureError, CameraDevice, OpenCVCameraSession


COLOR_LABELS = {
    "red": "红色",
    "green": "绿色",
    "blue": "蓝色",
    "yellow": "黄色",
}


def parse_color_names(value: str) -> List[str]:
    """Parse a comma-separated list of supported color names.

    Args:
        value: Names such as ``red,green``.

    Returns:
        Deduplicated lower-case names in input order.
    """

    names = list(dict.fromkeys(part.strip().lower() for part in value.split(",")))
    names = [name for name in names if name]
    unknown = [name for name in names if name not in DEFAULT_COLOR_SPECS]
    if not names or unknown:
        supported = ", ".join(DEFAULT_COLOR_SPECS)
        detail = ", ".join(unknown) if unknown else "空列表"
        raise argparse.ArgumentTypeError(
            "不支持的颜色 {0}；可选值：{1}".format(detail, supported)
        )
    return names


def parse_args() -> argparse.Namespace:
    """Parse image, camera, target-color and output arguments."""

    parser = argparse.ArgumentParser(
        description="识别图片或摄像头画面中的红、绿、蓝、黄色区域。"
    )
    parser.add_argument(
        "--image",
        type=Path,
        help="读取一张本地图片；不传时使用摄像头限时扫描。",
    )
    device_source = parser.add_mutually_exclusive_group()
    device_source.add_argument(
        "--device",
        type=int,
        default=None,
        help="OpenCV 摄像头编号；没有提供稳定路径时默认使用 0。",
    )
    device_source.add_argument(
        "--device-path",
        help=(
            "稳定 V4L2 摄像头路径，例如 "
            "/dev/v4l/by-id/...-video-index0。"
        ),
    )
    parser.add_argument("--width", type=int, default=640, help="摄像头画面宽度。")
    parser.add_argument("--height", type=int, default=480, help="摄像头画面高度。")
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="摄像头扫描最长秒数。",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.5,
        help="打开摄像头后的曝光预热秒数。",
    )
    parser.add_argument(
        "--colors",
        type=parse_color_names,
        default=list(DEFAULT_COLOR_SPECS),
        help="逗号分隔目标颜色：red,green,blue,yellow。",
    )
    parser.add_argument(
        "--min-area",
        type=float,
        default=project_config.OBSTACLE_COLOR_MIN_AREA,
        help="忽略小于该像素面积的色块。",
    )
    parser.add_argument(
        "--stable-frames",
        type=int,
        default=project_config.OBSTACLE_COLOR_CONFIRM_FRAMES,
        help="摄像头连续识别到同一主色多少帧后确认。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="标注图输出路径；默认保存到 captures/。",
    )
    return parser.parse_args()


def build_output_path(requested_path: Optional[Path]) -> Path:
    """Return the requested path or a timestamped path under captures/."""

    if requested_path is not None:
        return requested_path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("captures") / ("color_detection_{0}.jpg".format(timestamp))


def select_camera_device(args: argparse.Namespace) -> CameraDevice:
    """Return the stable camera path or numeric fallback selected by the CLI.

    Args:
        args: Parsed arguments containing ``device`` and ``device_path``.

    Returns:
        Stable V4L2 path when supplied; otherwise an integer camera index.
    """

    if args.device_path is not None:
        return args.device_path
    return args.device if args.device is not None else 0


def save_annotated_frame(cv2, detector: ColorDetector, frame, result, output: Path) -> None:
    """Draw the result and save it, creating the parent directory if needed.

    Args:
        cv2: Imported OpenCV module.
        detector: Detector that produced ``result``.
        frame: Original BGR image.
        result: Structured color detection result.
        output: Exact image output path.
    """

    output.parent.mkdir(parents=True, exist_ok=True)
    annotated = detector.annotate(frame, result)
    extension = output.suffix.lower() or ".jpg"
    encoded, image_bytes = cv2.imencode(extension, annotated)
    if not encoded:
        raise ColorDetectionError("无法保存标注图：{0}".format(output))
    # Path.write_bytes supports the Chinese Windows workspace path that some
    # OpenCV builds cannot handle through cv2.imwrite directly.
    output.write_bytes(image_bytes.tobytes())


def print_result(result: ColorDetectionResult, output: Path) -> None:
    """Print a concise Chinese summary and all detected regions."""

    dominant = result.dominant_color
    if dominant is None:
        print("未识别到满足面积阈值的目标颜色。")
    else:
        print("主颜色：{0} ({1})".format(COLOR_LABELS[dominant], dominant))
        print("识别区域数：{0}".format(len(result.regions)))
        for index, region in enumerate(result.regions, start=1):
            print(
                "  {0}. {1} center={2} area={3:.0f}px coverage={4:.2f}%".format(
                    index,
                    COLOR_LABELS[region.color],
                    region.center,
                    region.area,
                    region.coverage * 100.0,
                )
            )
    print("标注图：{0}".format(output.resolve()))


def run_image(args: argparse.Namespace, detector: ColorDetector, cv2) -> int:
    """Recognize one image and save its annotated result."""

    if not args.image.is_file():
        raise ColorDetectionError("图片不存在：{0}".format(args.image))
    # Decode bytes instead of passing a Unicode path into cv2.imread. This
    # keeps local Windows verification consistent with Raspberry Pi behavior.
    import numpy as np

    frame = cv2.imdecode(
        np.frombuffer(args.image.read_bytes(), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    if frame is None:
        raise ColorDetectionError("OpenCV 无法读取图片：{0}".format(args.image))

    # 1. Detect colors without touching any camera or GPIO resource.
    result = detector.detect(frame)
    # 2. Always save an annotated copy for threshold and lighting review.
    output = build_output_path(args.output)
    save_annotated_frame(cv2, detector, frame, result, output)
    print_result(result, output)
    return 0 if result.regions else 1


def run_camera(args: argparse.Namespace, detector: ColorDetector, cv2) -> int:
    """Scan the camera until a stable dominant color appears or timeout expires."""

    if args.timeout <= 0:
        raise ValueError("--timeout 必须大于 0")
    if args.stable_frames <= 0:
        raise ValueError("--stable-frames 必须大于 0")

    deadline = time.monotonic() + args.timeout
    selected_device = select_camera_device(args)
    previous_color = None
    consecutive_frames = 0
    print(
        "开始颜色识别：camera={0}, timeout={1:.1f}s, colors={2}".format(
            selected_device, args.timeout, ",".join(args.colors)
        ),
        flush=True,
    )

    # The camera context guarantees release on success, error and Ctrl+C.
    with OpenCVCameraSession(
        device_index=selected_device,
        width=args.width,
        height=args.height,
        warmup_frames=5,
        warmup_seconds=args.warmup_seconds,
    ) as camera:
        while time.monotonic() < deadline:
            # 1. Analyze the newest frame while hardware ownership stays here.
            frame = camera.read_frame()
            result = detector.detect(frame)
            dominant = result.dominant_color

            # 2. Require consecutive agreement to reduce single-frame noise.
            if dominant is not None and dominant == previous_color:
                consecutive_frames += 1
            elif dominant is not None:
                previous_color = dominant
                consecutive_frames = 1
            else:
                previous_color = None
                consecutive_frames = 0

            # 3. Save and return only after the configured stability threshold.
            if consecutive_frames >= args.stable_frames:
                output = build_output_path(args.output)
                save_annotated_frame(cv2, detector, frame, result, output)
                print_result(result, output)
                return 0

    print("超时前没有稳定识别到目标颜色。", file=sys.stderr)
    return 1


def main() -> int:
    """Run static-image or time-limited live-camera color recognition."""

    args = parse_args()
    try:
        import cv2

        detector = ColorDetector(colors=args.colors, min_area=args.min_area)
        if args.image is not None:
            return run_image(args, detector, cv2)
        return run_camera(args, detector, cv2)
    except ImportError as exc:
        print(
            "颜色识别失败：缺少 OpenCV；请安装 python3-opencv 和 python3-numpy。",
            file=sys.stderr,
        )
        return 1
    except (CameraCaptureError, ColorDetectionError, ValueError) as exc:
        print("颜色识别失败：{0}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n用户取消颜色识别，摄像头已释放。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
