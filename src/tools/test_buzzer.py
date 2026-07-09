"""Manual buzzer test for the real Raspberry Pi car.

Modes::

    # Basic beep test (no sensor needed).
    python -m src.tools.test_buzzer beep

    # Demo all status signals in sequence.
    python -m src.tools.test_buzzer signals

    # Manual radar test — enter distance values by hand.
    python -m src.tools.test_buzzer manual-radar

    # Real radar with the ultrasonic sensor.
    python -m src.tools.test_buzzer radar

    # Show usage.
    python -m src.tools.test_buzzer --help

Testing notes:
- The buzzer shares BCM pin 8 with the on-board button.  It will beep
  when you run any of these tests.
- For ``radar`` mode, hold an object in front of the sensor and move it
  closer / farther to hear the beep rate change.
"""

import argparse
import time
import sys

from src.hardware.buzzer import Buzzer


def parse_args():
    parser = argparse.ArgumentParser(description="Test the buzzer.")
    parser.add_argument(
        "mode",
        nargs="?",
        default="beep",
        choices=["beep", "signals", "manual-radar", "radar"],
        help=(
            "beep — single beep;  signals — demo all status sounds;  "
            "manual-radar — type distances;  radar — live sensor feed"
        ),
    )
    parser.add_argument(
        "--pin", type=int, default=None,
        help="BCM pin (default: config.BUZZER_PIN = 8)",
    )
    return parser.parse_args()


# ------------------------------------------------------------------
#  Modes
# ------------------------------------------------------------------

def mode_beep(buzzer):
    """Simple beep + pattern demo, no sensor needed."""
    print("  Single beep (0.2 s)")
    buzzer.beep(0.2)
    time.sleep(0.3)

    print("  Pattern: 3 quick beeps")
    buzzer.beep_pattern(3, 0.1, 0.1)
    time.sleep(0.3)

    print("  Long beep (1 s)")
    buzzer.beep(1.0)


def mode_signals(buzzer):
    """Play every status signal in sequence."""
    for name in ("startup", "obstacle", "arrival",
                  "photo", "complete", "error"):
        print(f"  signal_{name}() ...")
        getattr(buzzer, f"signal_{name}")()
        time.sleep(0.4)


def mode_manual_radar(buzzer):
    """Let the user type distances to hear the radar response."""
    print("  Manual reverse-radar.  Enter a distance in cm, or 'q' to quit.")
    print("  Try: 80  60  40  25  10  5")
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
        print(f"    radar_beep({d:.0f})")
        buzzer.radar_beep(d)
        # Small extra pause so the user can hear the pattern clearly.
        time.sleep(0.3)


def mode_radar(buzzer):
    """Live radar using the ultrasonic sensor."""
    print("  Live reverse-radar with UltrasonicSensor.")
    print("  Move an object toward / away from the sensor.")
    print("  Ctrl+C to stop.")
    print()
    # Lazy import so the user doesn't need RPi.GPIO if they only run
    # modes that don't need the sensor.
    from src.hardware.ultrasonic import UltrasonicSensor

    sensor = UltrasonicSensor()
    try:
        print("  Starting radar loop ...")
        buzzer.start_radar(sensor)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        buzzer.stop_radar()
        sensor.close()


# ------------------------------------------------------------------
#  Main
# ------------------------------------------------------------------

def main():
    args = parse_args()
    buzzer = Buzzer(pin=args.pin)

    try:
        # Dispatch.
        runner = {
            "beep": mode_beep,
            "signals": mode_signals,
            "manual-radar": mode_manual_radar,
            "radar": mode_radar,
        }[args.mode]
        runner(buzzer)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
    finally:
        buzzer.close()
        print("  Done.")


if __name__ == "__main__":
    main()
