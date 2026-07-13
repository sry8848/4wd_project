import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.hardware.camera import CameraCaptureError
from src.server.obstacle_recorder import ObstacleRecorder
from src.server.obstacle_store import ObstacleStore
from src.tasks.edge_follow import EDGE_RECOVERED_TO_START_NODE, EDGE_RECOVERY_FAILED


class ObstacleRecorderTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        now = datetime(2026, 7, 14, 8, 30, 0, 123456, tzinfo=timezone.utc)
        self.store = ObstacleStore(self.temp_dir.name, now_fn=lambda: now)

    def test_recovered_obstacle_captures_then_persists_real_image(self):
        camera = Mock()

        def capture(path):
            Path(path).write_bytes(b"jpeg")

        camera.capture.side_effect = capture
        recorder = ObstacleRecorder(self.store, camera)

        record = recorder.record(
            ride_id="ride-1",
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            recovery_status=EDGE_RECOVERED_TO_START_NODE,
        )

        self.assertEqual(record.status, "recovered")
        self.assertEqual(record.recovered_point, "C3")
        self.assertIsNotNone(record.image_url)
        self.assertIsNone(record.capture_error)
        camera.capture.assert_called_once()

    def test_capture_failure_still_persists_record_for_default_image(self):
        camera = Mock()
        camera.capture.side_effect = CameraCaptureError("camera unavailable")
        recorder = ObstacleRecorder(self.store, camera)

        record = recorder.record(
            ride_id="ride-1",
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            recovery_status=EDGE_RECOVERED_TO_START_NODE,
        )

        self.assertIsNone(record.image_url)
        self.assertEqual(record.capture_error, "camera unavailable")
        self.assertEqual(len(self.store.list_records()), 1)

    def test_recovery_failure_does_not_capture(self):
        camera = Mock()
        recorder = ObstacleRecorder(self.store, camera)

        record = recorder.record(
            ride_id="ride-1",
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            recovery_status=EDGE_RECOVERY_FAILED,
        )

        self.assertEqual(record.status, "recovery_failed")
        self.assertIsNone(record.recovered_point)
        self.assertIn("未执行抓拍", record.capture_error)
        camera.capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
