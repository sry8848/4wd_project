"""摄像头 MJPEG 实时预览服务。

用途：
    在电脑浏览器里查看树莓派摄像头画面，用于手动调焦、调整支架和观察曝光。

常用命令：
    python3 src/tools/stream_camera_mjpeg.py --device 1
    python3 src/tools/stream_camera_mjpeg.py \
        --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0

然后在电脑浏览器打开：
    http://树莓派IP:8080/
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Event, Lock
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware.camera import OpenCVCameraSettings, apply_opencv_camera_settings


def parse_args() -> argparse.Namespace:
    """解析 MJPEG 预览服务参数。"""

    parser = argparse.ArgumentParser(description="摄像头 MJPEG 实时预览服务。")
    camera_source = parser.add_mutually_exclusive_group()
    camera_source.add_argument(
        "--device", type=int, default=1, help="OpenCV 摄像头编号。"
    )
    camera_source.add_argument(
        "--device-path",
        type=Path,
        help="稳定的 V4L2 设备路径，例如 /dev/v4l/by-id/...-video-index0。",
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址。")
    parser.add_argument("--port", type=int, default=8080, help="监听端口。")
    parser.add_argument("--width", type=int, default=640, help="图像宽度。")
    parser.add_argument("--height", type=int, default=480, help="图像高度。")
    parser.add_argument("--fps", type=float, default=15, help="目标帧率。")
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
    parser.add_argument("--jpeg-quality", type=int, default=80, help="JPEG 质量，1 到 100。")
    return parser.parse_args()


def build_camera_settings(args: argparse.Namespace) -> OpenCVCameraSettings:
    """根据命令行参数构造 OpenCV 摄像头控制项。

    参数:
        args: 已解析的命令行参数。

    返回:
        OpenCVCameraSettings，供实时预览摄像头应用。
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
    """启动实时 MJPEG 预览服务。"""

    args = parse_args()
    try:
        import cv2
    except ImportError:
        print("未安装 OpenCV，无法启动实时预览。", file=sys.stderr)
        return 1

    selected_device = (
        str(args.device_path) if args.device_path is not None else args.device
    )
    camera = cv2.VideoCapture(selected_device)
    if not camera.isOpened():
        print(f"无法打开摄像头 {selected_device}", file=sys.stderr)
        return 1

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    apply_opencv_camera_settings(cv2, camera, build_camera_settings(args))
    camera_lock = Lock()
    stop_requested = Event()
    stream_failed = Event()

    class MjpegHandler(BaseHTTPRequestHandler):
        """把 OpenCV 画面输出为浏览器可看的 MJPEG 流。"""

        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><img src='/stream.mjpg' style='max-width:100%;'></body></html>"
                )
                return

            if self.path != "/stream.mjpg":
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            frame_delay = 1.0 / max(1.0, args.fps)
            while not stop_requested.is_set():
                # 浏览器刷新可能让两个 HTTP 请求短暂并存，必须串行读摄像头。
                with camera_lock:
                    ok, frame = camera.read()
                if not ok or frame is None:
                    if not stream_failed.is_set():
                        print(
                            f"摄像头 {selected_device} 读取失败，视频服务将退出。",
                            file=sys.stderr,
                            flush=True,
                        )
                        stream_failed.set()
                        stop_requested.set()
                        server.shutdown()
                    break
                ok, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), args.jpeg_quality],
                )
                if not ok:
                    continue
                data = encoded.tobytes()
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(data)
                    self.wfile.write(b"\r\n")
                    time.sleep(frame_delay)
                except (BrokenPipeError, ConnectionResetError):
                    break

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer((args.host, args.port), MjpegHandler)
    print(f"实时预览已启动: http://树莓派IP:{args.port}/", flush=True)
    print("按 Ctrl+C 退出。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_requested.set()
        with camera_lock:
            camera.release()
        server.server_close()
    return 1 if stream_failed.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
