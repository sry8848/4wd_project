"""Manual grid-navigation test for the real Raspberry Pi car.

Example:
    python3 -m src.tools.test_grid_navigation --rows 3 --cols 3 --start A1 --end C3 --heading east

Testing notes:
- First run the motor, line-sensor, and ultrasonic tests separately.
- Put the car on a black-line grid and start from a trusted node.
- Ctrl+C is handled by the outer finally path, which brakes and closes hardware.
"""

import argparse
import sys

from src.algorithms.astar import PASSABLE, format_path
from src.hardware.line_sensor import LineSensor
from src.hardware.motor import MotorController
from src.hardware.ultrasonic import UltrasonicSensor
from src.tasks.edge_follow import CachedObstacleSensor, EdgeFollower
from src.tasks.grid_navigation import (
    HEADING_EAST,
    HEADING_NORTH,
    HEADING_SOUTH,
    HEADING_WEST,
    GridNavigator,
)
from src.tasks.line_follow import LineFollower


HEADINGS = (HEADING_NORTH, HEADING_EAST, HEADING_SOUTH, HEADING_WEST)


def parse_args():
    parser = argparse.ArgumentParser(description="Run grid point-to-point navigation.")
    parser.add_argument("--rows", type=int, required=True, help="grid row count")
    parser.add_argument("--cols", type=int, required=True, help="grid column count")
    parser.add_argument("--start", required=True, help="start node, for example A1")
    parser.add_argument("--end", required=True, help="end node, for example C3")
    parser.add_argument("--heading", choices=HEADINGS, required=True, help="initial heading")
    parser.add_argument(
        "--blocked-edge",
        action="append",
        default=[],
        help="static blocked edge like A1-A2; can be passed multiple times",
    )
    parser.add_argument("--forward-speed", type=int, default=20)
    parser.add_argument("--line-turn-speed", type=int, default=80)
    parser.add_argument(
        "--line-left-turn-speed",
        type=int,
        default=None,
        help="left correction speed; defaults to --line-turn-speed",
    )
    parser.add_argument(
        "--line-right-turn-speed",
        type=int,
        default=None,
        help="right correction speed; defaults to --line-turn-speed",
    )
    parser.add_argument("--search-speed", type=int, default=8)
    parser.add_argument("--spin-speed", type=int, default=30)
    parser.add_argument("--turn-seconds", type=float, default=0.5)
    parser.add_argument("--uturn-seconds", type=float, default=1.2)
    parser.add_argument("--edge-timeout", type=float, default=5)
    parser.add_argument("--recovery-timeout", type=float, default=5)
    parser.add_argument("--delay", type=float, default=0.02)
    parser.add_argument("--threshold", type=int, default=None, help="ultrasonic obstacle threshold cm")
    parser.add_argument(
        "--no-ultrasonic",
        action="store_true",
        help="disable ultrasonic obstacle checks for pure line-following tests",
    )
    parser.add_argument(
        "--line-debug",
        action="store_true",
        help="print line sensor readings, node decision, action, and motor command every step",
    )
    return parser.parse_args()


def parse_coordinate(value):
    """把 A1 形式的节点名转换为零基 (row, col) 坐标。"""
    if len(value) < 2 or not value[0].isalpha() or not value[1:].isdigit():
        raise ValueError(f"无效节点坐标: {value}")

    row = ord(value[0].upper()) - ord("A")
    col = int(value[1:]) - 1
    return (row, col)


def validate_coordinate(name, coordinate, rows, cols):
    """确认坐标在命令行指定的矩形网格内。"""
    row, col = coordinate
    if row < 0 or row >= rows or col < 0 or col >= cols:
        raise ValueError(f"{name} 超出网格范围: {coordinate}")


def parse_blocked_edge(value, rows, cols):
    """解析 A1-A2 形式的静态封锁边。"""
    parts = value.split("-")
    if len(parts) != 2:
        raise ValueError(f"无效 blocked edge: {value}")

    first = parse_coordinate(parts[0])
    second = parse_coordinate(parts[1])
    validate_coordinate("blocked edge", first, rows, cols)
    validate_coordinate("blocked edge", second, rows, cols)
    if abs(first[0] - second[0]) + abs(first[1] - second[1]) != 1:
        raise ValueError(f"blocked edge 两端必须相邻: {value}")

    return frozenset({first, second})


def build_grid(rows, cols):
    """生成全可通行矩形网格。"""
    if rows <= 0 or cols <= 0:
        raise ValueError("--rows 和 --cols 必须大于 0")
    return [[PASSABLE for _ in range(cols)] for _ in range(rows)]


def main():
    args = parse_args()
    grid = build_grid(args.rows, args.cols)
    start = parse_coordinate(args.start)
    end = parse_coordinate(args.end)
    validate_coordinate("start", start, args.rows, args.cols)
    validate_coordinate("end", end, args.rows, args.cols)
    static_blocked_edges = {
        parse_blocked_edge(edge, args.rows, args.cols)
        for edge in args.blocked_edge
    }

    motor = None
    sensor = None
    ultrasonic = None
    try:
        motor = MotorController()
        sensor = LineSensor()
        obstacle_sensor = None
        if not args.no_ultrasonic:
            ultrasonic = UltrasonicSensor(threshold_cm=args.threshold)
            ultrasonic.start_monitoring()
            obstacle_sensor = CachedObstacleSensor(ultrasonic)
        line_follower = LineFollower(
            sensor,
            motor,
            forward_speed=args.forward_speed,
            turn_speed=args.line_turn_speed,
            left_turn_speed=args.line_left_turn_speed,
            right_turn_speed=args.line_right_turn_speed,
            search_speed=args.search_speed,
            debug_output=sys.stdout if args.line_debug else None,
        )
        edge_follower = EdgeFollower(
            line_follower,
            obstacle_sensor=obstacle_sensor,
            turn_speed=args.spin_speed,
            uturn_seconds=args.uturn_seconds,
            delay_seconds=args.delay,
        )
        navigator = GridNavigator(
            grid,
            edge_follower,
            motor,
            static_blocked_edges=static_blocked_edges,
            turn_speed=args.spin_speed,
            turn_seconds=args.turn_seconds,
            uturn_seconds=args.uturn_seconds,
            edge_max_seconds=args.edge_timeout,
            recovery_max_seconds=args.recovery_timeout,
        )

        print(f"grid: {args.rows}x{args.cols}")
        print(f"start={args.start} end={args.end} heading={args.heading}")
        print(f"static blocked edges: {len(static_blocked_edges)}")
        result = navigator.navigate(start, end, args.heading)
        print(f"navigation result: {result}")
        if navigator.current_node is not None:
            print(f"final node: {format_path([navigator.current_node])[0]}")
        print(f"dynamic blocked edges: {len(navigator.dynamic_blocked_edges)}")
    except KeyboardInterrupt:
        print("\n用户中断，停车并释放资源。")
    finally:
        if motor is not None:
            motor.brake()
        if sensor is not None:
            sensor.close()
        if ultrasonic is not None:
            ultrasonic.close()
        if motor is not None:
            motor.close()


if __name__ == "__main__":
    main()
