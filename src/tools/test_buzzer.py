"""Manual buzzer test for the real Raspberry Pi car.

Modes::

    # Basic beep test (no sensor needed).
    python -m src.tools.test_buzzer beep

    # Demo all status signals in sequence.
    python -m src.tools.test_buzzer signals

    # Show usage.
    python -m src.tools.test_buzzer --help

Testing notes:
- The buzzer shares BCM pin 8 with the on-board button.
- The ``beep`` and ``signals`` modes only use the buzzer — no sensor
  or motor required.
"""

import argparse
import time

from src.hardware.buzzer import Buzzer


def parse_args():
    parser = argparse.ArgumentParser(description="Test the buzzer (hardware only).")
    parser.add_argument(
        "mode",
        nargs="?",
        default="beep",
        choices=["beep", "signals"],
        help="beep — single beep;  signals — demo all status sounds",
    )
    parser.add_argument(
        "--pin", type=int, default=None,
        help="BCM pin (default: config.BUZZER_PIN = 8)",
    )
    return parser.parse_args()


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


def main():
    args = parse_args()
    buzzer = Buzzer(pin=args.pin)

    try:
        {"beep": mode_beep, "signals": mode_signals}[args.mode](buzzer)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
    finally:
        buzzer.close()
        print("  Done.")


if __name__ == "__main__":
    main()
