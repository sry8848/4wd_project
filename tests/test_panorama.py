"""Local verification for the retained car-turn panorama stitcher."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.panorama import PanoramaError, stitch_images


class PanoramaStitchingTest(unittest.TestCase):
    """Verify only the stitching boundary used by the car-turn tool."""

    def test_stitch_images_requires_two_sources(self):
        """A panorama cannot be constructed from a single source image."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(PanoramaError, "at least two images"):
                stitch_images([root / "one.jpg"], root / "panorama.jpg")

    def test_stitch_images_writes_successful_result(self):
        """The retained task passes source images to OpenCV and writes its result."""

        class FakeStitcher:
            def __init__(self):
                self.confidence = None

            def setPanoConfidenceThresh(self, value):
                self.confidence = value

            def stitch(self, images):
                self.test_case.assertEqual(
                    images,
                    ["image:first.jpg", "image:second.jpg"],
                )
                return 0, "panorama-data"

        stitcher = FakeStitcher()
        stitcher.test_case = self
        written = []
        fake_cv2 = SimpleNamespace(
            Stitcher_OK=0,
            Stitcher_PANORAMA=1,
            Stitcher_create=lambda _mode: stitcher,
            imread=lambda path: f"image:{Path(path).name}",
            imwrite=lambda path, image: written.append((path, image)) or True,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result" / "panorama.jpg"
            with patch.dict(sys.modules, {"cv2": fake_cv2}):
                result = stitch_images(
                    [root / "first.jpg", root / "second.jpg"],
                    output,
                    confidence_threshold=0.25,
                )

            self.assertEqual(result, output)
            self.assertEqual(stitcher.confidence, 0.25)
            self.assertEqual(written, [(str(output), "panorama-data")])


if __name__ == "__main__":
    unittest.main()
