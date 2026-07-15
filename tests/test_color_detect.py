"""Local verification for HSV color detection without Raspberry Pi hardware."""

import pytest


cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from src.algorithms.color_detect import ColorDetector


@pytest.mark.parametrize(
    "color,bgr",
    [
        ("red", (0, 0, 255)),
        ("red", (120, 108, 188)),
        ("green", (0, 255, 0)),
        ("blue", (255, 0, 0)),
        ("yellow", (0, 255, 255)),
    ],
)
def test_detects_supported_color_blocks(color, bgr):
    """Each default HSV range recognizes a large pure BGR color block."""

    frame = np.zeros((200, 300, 3), dtype=np.uint8)
    cv2.rectangle(frame, (50, 40), (250, 160), bgr, -1)

    result = ColorDetector(min_area=1000).detect(frame)

    assert result.dominant_color == color
    assert result.regions[0].center == (150, 100)
    assert result.regions[0].area >= 23000


def test_ignores_regions_below_minimum_area():
    """The area threshold filters isolated colored noise."""

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(frame, (10, 10), (20, 20), (0, 0, 255), -1)

    result = ColorDetector(min_area=500).detect(frame)

    assert result.regions == ()


def test_rejects_unknown_color_name():
    """Configuration errors fail before a camera scan starts."""

    with pytest.raises(ValueError, match="unsupported color"):
        ColorDetector(colors=["purple"])
