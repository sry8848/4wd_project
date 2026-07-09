"""Safe driving-lights test — LED only, no motor movement.

Shows the colour that would appear for each action without actually
driving the motors.  Useful for verifying the LED logic on a workbench.

Usage::

    python3 -m src.tools.test_driving_lights_safe
"""

from src.hardware.led import RgbLed
import time

led = RgbLed()
try:
    print("  Forward  → 🟢 green")
    led.green()
    time.sleep(1)

    print("  Backward → 🔴 red")
    led.red()
    time.sleep(1)

    print("  Turn     → 🟡 yellow")
    led.yellow()
    time.sleep(1)

    print("  Stopped  → ⚫ off")
    led.off()
    time.sleep(1)

    print("  Done.")
finally:
    led.close()
