"""Manual reverse-radar task test for the real Raspberry Pi car.

Modes::

    # Enter distance values by hand to hear the beep pattern.
    python -m src.tools.test_reverse_radar manual

    # Live radar with the ultrasonic sensor.
    python -m src.tools.test_reverse_radar live

    # Show usage.
    python -m src.tools.test_reverse_radar --help

Testing notes:
- ``manual`` mode does not require the ultrasonic sensor.
- ``live`` mode requires the sensor.  Move an object closer / farther
  to hear the beep rate change.
- The buzzer sounds during the test.
"""

import argparse
import time

from src.tasks.reverse_radar import ReverseRadar


def parse_args():
    parser = argparse.ArgumentParser(description="Test the reverse-radar task.")
    parser.add_argument(
        "mode",
        nargs="?",
        default="manual",
        choices=["manual", "live"],
        help="manual — type distances;  live — use ultrasonic sensor",
    )
    return parser.parse_args()


def mode_manual():
    """Type distances manually — no sensor needed."""
    print("  Manual reverse-radar.  Enter a distance in cm, or 'q' to quit.")
    print("  Try: 80  60  40  25  10  5")
    radar = ReverseRadar()
    try:
        while True:
            try:
                inp = input("  cm > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not inp or inp.lower() in ("q", "quit", "exit"):
                break
            try:
                d = float(inp)
            except ValueError:
                print(f"  ignoring '{inp}' — enter a number")
                continue
            print(f"  radar_beep({d:.0f})")
            radar.radar_beep(d)
            time.sleep(0.3)
    finally:
        radar.close()
        print("  Done.")


def mode_live():
    """Live radar using the ultrasonic sensor."""
    print("  Live reverse-radar with UltrasonicSensor.")
    print("  Move an object toward / away from the sensor.")
    print("  Ctrl+C to stop.")
    print()

    radar = ReverseRadar()
    try:
        print("  Starting radar loop ...")
        radar.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        radar.close()
        print("  Done.")


def main():
    args = parse_args()
    try:
        if args.mode == "manual":
            mode_manual()
        else:
            mode_live()
    except KeyboardInterrupt:
        print("\n  Interrupted.")


if __name__ == "__main__":
    main()
