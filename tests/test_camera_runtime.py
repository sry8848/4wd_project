import unittest
from pathlib import Path
from unittest.mock import Mock

from src.hardware.camera import CameraCaptureError, CaptureResult
from src.server.camera_runtime import BackendCamera, parse_camera_device


class BackendCameraTest(unittest.TestCase):
    def test_start_keeps_one_session_and_capture_reuses_it(self):
        session = Mock()
        session.capture.return_value = CaptureResult(
            path=Path("capture.jpg"),
            width=640,
            height=480,
            device_index=1,
            backend="opencv",
        )
        factory = Mock(return_value=session)
        camera = BackendCamera(device=1, session_factory=factory)

        self.assertTrue(camera.start())
        self.assertTrue(camera.available)
        self.assertEqual(camera.capture("capture.jpg"), Path("capture.jpg"))

        factory.assert_called_once_with(device_index=1)
        session.open.assert_called_once_with()
        session.capture.assert_called_once_with("capture.jpg", warmup_frames=1)

    def test_start_failure_does_not_raise_or_retry(self):
        session = Mock()
        session.open.side_effect = CameraCaptureError("cannot open")
        camera = BackendCamera(session_factory=Mock(return_value=session))

        self.assertFalse(camera.start())
        self.assertFalse(camera.available)
        self.assertEqual(camera.error, "cannot open")
        with self.assertRaisesRegex(CameraCaptureError, "cannot open"):
            camera.capture("capture.jpg")
        with self.assertRaisesRegex(RuntimeError, "只能启动一次"):
            camera.start()

        session.close.assert_called_once_with()

    def test_runtime_failure_closes_session_until_backend_restart(self):
        session = Mock()
        session.capture.side_effect = CameraCaptureError("read failed")
        camera = BackendCamera(session_factory=Mock(return_value=session))
        camera.start()

        with self.assertRaisesRegex(CameraCaptureError, "read failed"):
            camera.capture("capture.jpg")
        with self.assertRaisesRegex(CameraCaptureError, "read failed"):
            camera.capture("second.jpg")

        self.assertFalse(camera.available)
        session.close.assert_called_once_with()
        session.capture.assert_called_once_with("capture.jpg", warmup_frames=1)

    def test_parse_camera_device_accepts_one_number_or_path(self):
        self.assertEqual(parse_camera_device({}), 0)
        self.assertEqual(parse_camera_device({"CAMERA_DEVICE": "1"}), 1)
        self.assertEqual(
            parse_camera_device({"CAMERA_DEVICE": "/dev/video-obstacle"}),
            "/dev/video-obstacle",
        )
        with self.assertRaisesRegex(RuntimeError, "不能为空"):
            parse_camera_device({"CAMERA_DEVICE": "  "})


if __name__ == "__main__":
    unittest.main()
