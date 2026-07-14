"""实机判断小车运动期间 USB 摄像头是否掉线。

示例:
    python3 src/tools/test_camera_while_moving.py \
        --device-path /dev/v4l/by-id/usb-lihappe8_Corp._Sanhao_Face-video-index0 \
        --enable-motor-motion

测试会先静止读帧，再交替前进、停车、后退、停车。连续读帧失败，或
OpenCV 阻塞但在超时时间内没有新帧时，小车都会立即刹车并输出 fail。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config
from src.hardware.camera import (
    CameraCaptureError,
    OpenCVCameraSession,
    OpenCVCameraSettings,
)
from src.hardware.motor import MotorController
from src.tasks.camera_motion_stability import run_camera_motion_stability_test


def parse_args() -> argparse.Namespace:
    """解析摄像头、电机动作和报告输出参数。"""

    parser = argparse.ArgumentParser(
        description="边驱动小车边连续读帧，判断 USB 摄像头是否掉线。"
    )
    device_source = parser.add_mutually_exclusive_group()
    device_source.add_argument(
        "--device-path",
        default=config.CAMERA_DEVICE_PATH,
        help="稳定的 V4L2 摄像头路径。",
    )
    device_source.add_argument(
        "--device",
        type=int,
        help="临时摄像头编号；已知稳定路径可用时不推荐。",
    )
    parser.add_argument("--width", type=int, default=640, help="请求图像宽度。")
    parser.add_argument("--height", type=int, default=480, help="请求图像高度。")
    parser.add_argument("--fps", type=float, default=15, help="请求摄像头帧率。")
    parser.add_argument(
        "--speed",
        type=float,
        default=35,
        help="左右轮 PWM 占空比，安全上限为 60。",
    )
    parser.add_argument(
        "--move-seconds",
        type=float,
        default=1.0,
        help="每次前进或后退时长，安全上限为 3 秒。",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=1.0,
        help="动作间的停车监测时长。",
    )
    parser.add_argument(
        "--baseline-seconds",
        type=float,
        default=3.0,
        help="开始运动前的静止监测时长。",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=3,
        help="前进和后退组合动作的次数，安全上限为 10。",
    )
    parser.add_argument(
        "--failure-threshold",
        type=int,
        default=3,
        help="连续多少次读帧失败后判为掉线。",
    )
    parser.add_argument(
        "--no-frame-timeout",
        type=float,
        default=2.0,
        help="无新帧多少秒后由独立看门狗刹车，默认 2 秒。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("captures/camera_motion_stability"),
        help="JSON 测试报告保存目录。",
    )
    parser.add_argument(
        "--enable-motor-motion",
        action="store_true",
        help="安全确认开关；未提供时不会初始化或驱动电机。",
    )
    return parser.parse_args()


def main() -> int:
    """打开摄像头和电机，执行限时测试并保存 JSON 报告。"""

    args = parse_args()
    if not args.enable_motor_motion:
        print(
            "拒绝启动电机：请确认场地空旷并有人可随时断电，然后添加 "
            "--enable-motor-motion。",
            file=sys.stderr,
        )
        return 2

    selected_device = args.device if args.device is not None else args.device_path
    if args.device is None and not Path(args.device_path).exists():
        print(f"摄像头稳定路径不存在: {args.device_path}", file=sys.stderr)
        print("请重新插拔摄像头并用 readlink -f 核对路径。", file=sys.stderr)
        return 1

    camera = None
    motor = None
    try:
        # 先独占并预热摄像头，确认静止状态可读后才允许初始化电机。
        camera = OpenCVCameraSession(
            device_index=selected_device,
            width=args.width,
            height=args.height,
            warmup_frames=5,
            warmup_seconds=0.5,
            settings=OpenCVCameraSettings(
                fps=args.fps,
                fourcc="MJPG",
                buffer_size=1,
            ),
        ).open()
        motor = MotorController()

        print("测试开始：请勿同时启动视频流、拍照或颜色识别进程。", flush=True)
        print(f"摄像头: {selected_device}", flush=True)
        result = run_camera_motion_stability_test(
            motor=motor,
            camera=camera,
            speed=args.speed,
            move_seconds=args.move_seconds,
            pause_seconds=args.pause_seconds,
            baseline_seconds=args.baseline_seconds,
            cycles=args.cycles,
            failure_threshold=args.failure_threshold,
            no_frame_timeout=args.no_frame_timeout,
            log=lambda message: print(message, flush=True),
        )
    except CameraCaptureError as exc:
        print(f"摄像头测试无法启动: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("收到 Ctrl+C，正在安全停车。", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"测试失败: {exc}", file=sys.stderr)
        return 1
    finally:
        # 资源由入口统一关闭；电机必须先停车，之后才释放摄像头。
        if motor is not None:
            motor.close()
        if camera is not None:
            camera.close()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.output_dir / f"camera_motion_{timestamp}.json"
    report = {
        "camera_device": str(selected_device),
        "width": args.width,
        "height": args.height,
        "requested_fps": args.fps,
        "speed": args.speed,
        "move_seconds": args.move_seconds,
        "pause_seconds": args.pause_seconds,
        "baseline_seconds": args.baseline_seconds,
        "cycles": args.cycles,
        "failure_threshold": args.failure_threshold,
        "no_frame_timeout": args.no_frame_timeout,
        "result": asdict(result),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n测试结果")
    print(f"verdict={result.verdict}")
    print(f"elapsed_seconds={result.elapsed_seconds}")
    print(f"frames_read={result.frames_read}")
    print(f"read_failures={result.read_failures}")
    print(f"max_consecutive_failures={result.max_consecutive_failures}")
    print(f"stopped_early={result.stopped_early}")
    print(f"detection_mode={result.detection_mode}")
    print(f"last_frame_elapsed_seconds={result.last_frame_elapsed_seconds}")
    print(f"last_frame_phase={result.last_frame_phase}")
    print(f"suspected_trigger_phase={result.suspected_trigger_phase}")
    print(
        "stall_detected_elapsed_seconds="
        f"{result.stall_detected_elapsed_seconds}"
    )
    print(f"stall_detected_phase={result.stall_detected_phase}")
    print(
        "no_frame_seconds_at_detection="
        f"{result.no_frame_seconds_at_detection}"
    )
    print(f"reader_thread_blocked={result.reader_thread_blocked}")
    if result.failure_reason:
        print(f"failure_reason={result.failure_reason}")
    print(f"report={report_path}")

    if result.verdict == "pass":
        print("结论：本轮运动测试未检测到摄像头读帧异常。")
        return 0
    if result.verdict == "warning":
        print("结论：出现瞬时读帧失败但已恢复，建议重复测试并检查供电和 USB 接头。")
        return 2

    if result.detection_mode == "no-frame-watchdog":
        print(
            "停帧定位：最后成功帧位于 "
            f"{result.last_frame_phase}，最可能从 "
            f"{result.suspected_trigger_phase} 开始停止出帧。",
            file=sys.stderr,
        )
        if result.reader_thread_blocked:
            print(
                "OpenCV read() 在刹车时仍处于阻塞状态；No such device "
                "可能稍后才返回，判定没有等待该错误。",
                file=sys.stderr,
            )
    print("结论：检测到摄像头掉线或监测线程失去响应。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
