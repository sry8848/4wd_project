import unittest

from src.hardware.line_sensor import LineReading
from src.tools.test_line_sensor import format_reading


class LineSensorToolTest(unittest.TestCase):
    def test_format_reading_marks_black_and_white_for_each_sensor(self):
        text = format_reading(LineReading(True, False, True, False))

        self.assertEqual(
            text,
            "left_outer=black left_inner=white right_inner=black right_outer=white",
        )


if __name__ == "__main__":
    unittest.main()
