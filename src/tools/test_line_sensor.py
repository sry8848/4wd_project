"""Manual read-only test for the four line tracking sensors.

Usage on Raspberry Pi:
    python3 -m src.tools.test_line_sensor --count 20 --interval 0.2
"""

import argparse
import time

from src.hardware.line_sensor import LineSensor


def format_reading(reading):
    """把四路巡线读数格式化为一行易观察文本。

    参数说明：
    reading: src.hardware.line_sensor.LineReading 实例。
    """
    # black 表示该路传感器检测到黑线，white 表示没有检测到黑线。
    left_outer = "black" if reading.left_outer else "white"
    left_inner = "black" if reading.left_inner else "white"
    right_inner = "black" if reading.right_inner else "white"
    right_outer = "black" if reading.right_outer else "white"
    return (
        f"left_outer={left_outer} "
        f"left_inner={left_inner} "
        f"right_inner={right_inner} "
        f"right_outer={right_outer}"
    )


def main():
    """持续读取四路循迹传感器并打印归一化结果。"""
    parser = argparse.ArgumentParser(description="Print line sensor values.")
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="number of readings to print; omit to keep reading until Ctrl+C",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.2,
        help="seconds between reads",
    )
    args = parser.parse_args()

    if args.count is not None and args.count <= 0:
        parser.error("--count 必须大于 0")
    if args.interval <= 0:
        parser.error("--interval 必须大于 0")

    sensor = LineSensor()
    reads = 0
    try:
        while args.count is None or reads < args.count:
            print(format_reading(sensor.read()))
            reads += 1
            time.sleep(args.interval)
    finally:
        sensor.close()


if __name__ == "__main__":
    main()
