"""Manual driving-lights test for the real Raspberry Pi car.

Modes::

    # Test each action with LED colour (short, safe bursts).
    python -m src.tools.test_driving_lights

    # Custom action.
    python -m src.tools.test_driving_lights forward --speed 40 --duration 0.5

Testing notes:
- The wheels move during this test — lift the car or keep it on the
  ground with a short duration.
- Watch the LED colour change with each action:
    forward  → 🟢 green
    backward → 🔴 red
    left     → 🟡 yellow
    right    → 🟡 yellow
    spin     → 🟡 yellow
    brake    → ⚫ off
"""

import argparse
import time
import sys

from src.tasks.driving_lights import DrivingLights


def parse_args():
    parser = argparse.ArgumentParser(description="Test driving lights.")
    parser.add_argument(
        "action",
        nargs="?",
        default="all",
        choices=["all", "forward", "backward", "left", "right",
                 "spin-left", "spin-right"],
        help="all — run every action briefly (default);  or pick one",
    )
    parser.add_argument("--speed", type=int, default=30,
                        help="PWM duty 0-100 (default 30)")
    parser.add_argument("--duration", type=float, default=0.5,
                        help="Seconds per action (default 0.5)")
    return parser.parse_args()


_ACTION_NAMES = {
    "forward": "forward",
    "backward": "backward",
    "left": "left",
    "right": "right",
    "spin-left": "spin_left",
    "spin-right": "spin_right",
}


def run_one(dl, name, speed, duration):
    """Run one action with colour annotation."""
    labels = {
        "forward":     "🟢 forward",
        "backward":    "🔴 backward",
        "left":        "🟡 left",
        "right":       "🟡 right",
        "spin_left":   "🟡 spin-left",
        "spin_right":  "🟡 spin-right",
    }
    method = getattr(dl, name)
    print(f"  {labels[name]}  (speed={speed}, {duration}s)")
    method(speed, speed)
    time.sleep(duration)
    dl.brake()
    time.sleep(0.3)


def main():
    args = parse_args()
    dl = DrivingLights()

    try:
        if args.action == "all":
            print(f"  Driving lights demo  (speed={args.speed}, {args.duration}s each)")
            print("─" * 45)
            for act in _ACTION_NAMES:
                run_one(dl, _ACTION_NAMES[act], args.speed, args.duration)
            print("─" * 45)
            print("  All actions completed.")
        else:
            run_one(dl, _ACTION_NAMES[args.action], args.speed, args.duration)

    except KeyboardInterrupt:
        print("\n  Interrupted.")
    finally:
        dl.brake()
        dl.close()
        print("  Stopped and cleaned up.")


if __name__ == "__main__":
    main()
