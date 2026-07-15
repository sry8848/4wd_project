import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.hardware.camera import CameraCaptureError, CaptureResult
from src.server.camera_runtime import BackendCamera, parse_camera_device


class BackendCameraTest(unittest.TestCase):
    def test_probe_reads_one_frame_then_releases_handle(self):
        session = Mock()
        session.read_frame.return_value = object()
        factory = Mock(return_value=session)
        camera = BackendCamera(device=1, session_factory=factory)

        self.assertTrue(camera.probe())

        self.assertTrue(camera.ready)
        self.assertIsNone(camera.error)
        factory.assert_called_once_with(device_index=1, width=640, height=480)
        session.open.assert_called_once_with()
        session.read_frame.assert_called_once_with(copy=True)
        session.close.assert_called_once_with()

    def test_reads_reuse_one_handle_until_task_closes_it(self):
        frame = object()
        session = Mock()
        session.read_frame.return_value = frame
        factory = Mock(return_value=session)
        camera = BackendCamera(device="/dev/camera", session_factory=factory)

        self.assertIs(camera.read_frame(), frame)
        self.assertIs(camera.read_frame(), frame)
        camera.close()

        factory.assert_called_once_with(
            device_index="/dev/camera",
            width=640,
            height=480,
        )
        session.open.assert_called_once_with()
        self.assertEqual(session.read_frame.call_count, 2)
        session.close.assert_called_once_with()

    def test_read_failure_releases_stale_handle_and_next_read_reopens(self):
        failed_session = Mock()
        failed_session.read_frame.side_effect = CameraCaptureError("frame failed")
        recovered_frame = object()
        recovered_session = Mock()
        recovered_session.read_frame.return_value = recovered_frame
        factory = Mock(side_effect=[failed_session, recovered_session])
        camera = BackendCamera(session_factory=factory)

        with self.assertRaisesRegex(CameraCaptureError, "frame failed"):
            camera.read_frame()

        self.assertFalse(camera.ready)
        self.assertEqual(camera.error, "frame failed")
        failed_session.close.assert_called_once_with()

        self.assertIs(camera.read_frame(), recovered_frame)
        self.assertTrue(camera.ready)
        self.assertIsNone(camera.error)
        self.assertEqual(factory.call_count, 2)
        recovered_session.open.assert_called_once_with()

    def test_probe_failure_does_not_block_later_task_attempt(self):
        failed_session = Mock()
        failed_session.open.side_effect = CameraCaptureError("cannot open")
        recovered_frame = object()
        recovered_session = Mock()
        recovered_session.read_frame.return_value = recovered_frame
        camera = BackendCamera(
            session_factory=Mock(side_effect=[failed_session, recovered_session])
        )

        self.assertFalse(camera.probe())
        self.assertFalse(camera.ready)
        self.assertEqual(camera.error, "cannot open")
        failed_session.close.assert_called_once_with()

        self.assertIs(camera.read_frame(), recovered_frame)
        self.assertTrue(camera.ready)
        self.assertIsNone(camera.error)

    def test_next_task_opens_a_new_handle_after_close(self):
        first_session = Mock()
        first_session.read_frame.return_value = "first"
        second_session = Mock()
        second_session.read_frame.return_value = "second"
        factory = Mock(side_effect=[first_session, second_session])
        camera = BackendCamera(session_factory=factory)

        self.assertEqual(camera.read_frame(), "first")
        camera.close()
        self.assertEqual(camera.read_frame(), "second")
        camera.close()

        self.assertEqual(factory.call_count, 2)
        first_session.close.assert_called_once_with()
        second_session.close.assert_called_once_with()

    def test_capture_is_one_shot_and_failure_can_be_retried(self):
        failed_session = Mock()
        failed_session.capture.side_effect = CameraCaptureError("capture failed")
        recovered_session = Mock()
        recovered_session.capture.return_value = CaptureResult(
            path=Path("second.jpg"),
            width=640,
            height=480,
            device_index=0,
            backend="opencv",
        )
        camera = BackendCamera(
            session_factory=Mock(side_effect=[failed_session, recovered_session])
        )

        with self.assertRaisesRegex(CameraCaptureError, "capture failed"):
            camera.capture("first.jpg")
        self.assertFalse(camera.ready)
        failed_session.close.assert_called_once_with()

        self.assertEqual(camera.capture("second.jpg"), Path("second.jpg"))
        self.assertTrue(camera.ready)
        self.assertIsNone(camera.error)
        recovered_session.close.assert_called_once_with()

    def test_save_frame_does_not_require_an_open_camera_handle(self):
        camera = BackendCamera(session_factory=Mock())
        frame = object()
        saved = SimpleNamespace(path=Path("capture.jpg"))

        with patch(
            "src.server.camera_runtime.write_diagnostic_frame",
            return_value=saved,
        ) as writer:
            self.assertEqual(
                camera.save_frame("capture.jpg", frame),
                Path("capture.jpg"),
            )

        writer.assert_called_once_with("capture.jpg", frame)
        self.assertFalse(camera.ready)

    def test_save_failure_does_not_change_camera_health(self):
        session = Mock()
        session.read_frame.return_value = object()
        camera = BackendCamera(session_factory=Mock(return_value=session))
        camera.read_frame()
        camera.close()

        with patch(
            "src.server.camera_runtime.write_diagnostic_frame",
            side_effect=CameraCaptureError("write failed"),
        ):
            with self.assertRaisesRegex(CameraCaptureError, "write failed"):
                camera.save_frame("capture.jpg", object())

        self.assertTrue(camera.ready)
        self.assertIsNone(camera.error)
        session.close.assert_called_once_with()

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
