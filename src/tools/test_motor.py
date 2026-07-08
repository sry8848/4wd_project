"""Manual motor smoke test for the real Raspberry Pi car.

Run one action at a time while the wheels are lifted.
Example:
    python -m src.tools.test_motor forward --speed 30 --duration 0.3
"""

import argparse
import time

from src.hardware.motor import MotorController


ACTION_TO_METHOD = {
    "forward": "forward",
    "backward": "backward",
    "left": "left",
    "right": "right",
    "spin-left": "spin_left",
    "spin-right": "spin_right",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Run one short motor action.")
    parser.add_argument("action", choices=ACTION_TO_METHOD.keys())
    parser.add_argument(
        "--speed",
        type=int,
        default=30,
        help="PWM duty cycle from 0 to 100. Default: 30.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.3,
        help="Action duration in seconds. Default: 0.3.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.duration <= 0 or args.duration > 2:
        raise ValueError("duration 必须大于 0 且不超过 2 秒")

    motor = MotorController()
    try:
        # 这里只执行一个动作，便于实机确认方向是否符合命令名称。
        action = getattr(motor, ACTION_TO_METHOD[args.action])
        action(args.speed, args.speed)
        time.sleep(args.duration)
    finally:
        motor.close()


if __name__ == "__main__":
    main()
