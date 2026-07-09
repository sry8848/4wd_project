"""Manual RGB LED test for the real Raspberry Pi car.

Modes::

    # Cycle through all 8 named colours.
    python -m src.tools.test_led colors

    # Demo all status signals in sequence.
    python -m src.tools.test_led signals

    # Blink test at custom speed.
    python -m src.tools.test_led blink

    # Show usage.
    python -m src.tools.test_led --help

Testing notes:
- The LED is mounted on the car chassis, visible during normal operation.
- No sensor or motor required for any of these tests.
"""

import argparse
import time

from src.hardware.led import RgbLed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test the RGB LED (hardware only)."
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="colors",
        choices=["colors", "signals", "blink"],
        help="colors — cycle named colours;  signals — status demos;  blink — flash",
    )
    return parser.parse_args()


def mode_colors(led):
    """Show every named colour with a 0.6 s pause."""
    for name, rgb in RgbLed.COLORS.items():
        print(f"  {name:8s}  ({rgb[0]:3d}, {rgb[1]:3d}, {rgb[2]:3d})")
        led.set_color_name(name)
        time.sleep(0.6)


def mode_signals(led):
    """Play every status signal in sequence."""
    for name in ("startup", "obstacle", "arrival",
                  "photo", "complete", "error"):
        print(f"  signal_{name}() ...")
        getattr(led, f"signal_{name}")()
        time.sleep(0.4)


def mode_blink(led):
    """Custom blink demo."""
    print("  Red blink, 5 times, fast")
    led.blink(5, 0.1, 0.1, "red")
    time.sleep(0.5)

    print("  Green blink, 3 times, slow")
    led.blink(3, 0.4, 0.3, "green")
    time.sleep(0.5)

    print("  Purple → off, 4 times")
    led.blink(4, 0.2, 0.2, "purple")


def main():
    args = parse_args()
    led = RgbLed()

    try:
        {"colors": mode_colors, "signals": mode_signals, "blink": mode_blink}[args.mode](led)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
    finally:
        led.close()
        print("  Done.")


if __name__ == "__main__":
    main()
