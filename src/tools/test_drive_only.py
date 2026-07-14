"""只驱动电机、不打开摄像头或读取传感器的实机测试。

示例:
    python3 src/tools/test_drive_only.py \
        --speed 35 --move-seconds 1 --pause-seconds 1 --cycles 3 \
        --enable-motor-motion
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.hardware.motor import MotorController
from src.tasks.drive_cycle import run_forward_backward_cycles


def parse_args() -> argparse.Namespace:
    """解析纯运动测试的速度、时间和安全确认参数。"""

    parser = argparse.ArgumentParser(
        description="仅执行前进和后退循环，不打开摄像头或读取传感器。"
    )
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
        help="相邻运动动作之间的停车时长。",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=3,
        help="前进和后退组合动作的次数，安全上限为 10。",
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=3.0,
        help="开始运动前的安全等待时间，范围 0 到 10 秒。",
    )
    parser.add_argument(
        "--enable-motor-motion",
        action="store_true",
        help="安全确认开关；未提供时不会初始化或驱动电机。",
    )
    return parser.parse_args()


def main() -> int:
    """初始化电机，执行纯运动循环并在最外层释放 GPIO。"""

    args = parse_args()
    if not args.enable_motor_motion:
        print(
            "拒绝启动电机：请确认场地安全，然后添加 --enable-motor-motion。",
            file=sys.stderr,
        )
        return 2
    if args.start_delay < 0 or args.start_delay > 10:
        print("start_delay 必须在 0 到 10 秒之间。", file=sys.stderr)
        return 2

    print("纯运动测试：不会打开摄像头，也不会读取任何传感器。", flush=True)
    print(
        f"{args.start_delay:.1f} 秒后开始，请确保前后方向没有障碍物。",
        flush=True,
    )

    motor = None
    try:
        if args.start_delay > 0:
            time.sleep(args.start_delay)
        motor = MotorController()
        run_forward_backward_cycles(
            motor=motor,
            speed=args.speed,
            move_seconds=args.move_seconds,
            pause_seconds=args.pause_seconds,
            cycles=args.cycles,
            log=lambda message: print(message, flush=True),
        )
    except KeyboardInterrupt:
        print("收到 Ctrl+C，正在安全停车。", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"纯运动测试失败: {exc}", file=sys.stderr)
        return 1
    finally:
        if motor is not None:
            motor.close()

    print("纯运动测试完成，小车已停车并释放 GPIO。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
