import tempfile
import unittest
from pathlib import Path

from src.hardware.camera import CameraCaptureError, OpenCVCameraSession


class FakeGrayFrame:
    def mean(self):
        return 73.5


class FakeLaplacian:
    def var(self):
        return 128.25


class FakeFrame:
    shape = (480, 640, 3)


class FakeCV2:
    COLOR_BGR2GRAY = 1
    CV_64F = 2

    def __init__(self, write_ok=True):
        self.write_ok = write_ok
        self.writes = []

    def imwrite(self, path, frame):
        self.writes.append((path, frame))
        return self.write_ok

    @staticmethod
    def cvtColor(_frame, _code):
        return FakeGrayFrame()

    @staticmethod
    def Laplacian(_gray, _depth):
        return FakeLaplacian()


class CameraFrameDiagnosticsTest(unittest.TestCase):
    def build_open_session(self, cv2):
        session = OpenCVCameraSession()
        session._camera = object()
        session._cv2 = cv2
        return session

    def test_save_diagnostic_frame_reports_path_and_image_quality(self):
        cv2 = FakeCV2()
        session = self.build_open_session(cv2)
        frame = FakeFrame()

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "nested" / "qr_timeout.jpg"
            result = session.save_diagnostic_frame(target, frame)

        self.assertEqual(result.path, target)
        self.assertEqual((result.width, result.height), (640, 480))
        self.assertEqual(result.mean_brightness, 73.5)
        self.assertEqual(result.sharpness, 128.25)
        self.assertEqual(cv2.writes, [(str(target), frame)])

    def test_save_diagnostic_frame_reports_write_failure(self):
        session = self.build_open_session(FakeCV2(write_ok=False))

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "qr_timeout.jpg"
            with self.assertRaisesRegex(CameraCaptureError, "Failed to write"):
                session.save_diagnostic_frame(target, FakeFrame())


if __name__ == "__main__":
    unittest.main()
