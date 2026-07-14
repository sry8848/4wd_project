import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.hardware.camera import CameraCaptureError
from src.server.obstacle_recorder import ObstacleRecorder
from src.server.obstacle_store import (
    HANDLING_BLOCKED_AND_REPLANNED,
    HANDLING_RECOVERY_FAILED,
    RECOVERED,
    RECOVERY_FAILED,
    ObstacleStore,
)


def visual_result(frame=object(), **overrides):
    values = {
        "obstacle_type": "ordinary",
        "detected_color": "red",
        "classification_status": "success",
        "station_id": None,
        "recognition_error": None,
        "record_frame": frame,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ObstacleRecorderTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        now = datetime(2026, 7, 14, 8, 30, 0, 123456, tzinfo=timezone.utc)
        self.store = ObstacleStore(self.temp_dir.name, now_fn=lambda: now)

    def test_saves_the_exact_classification_frame_and_strict_record(self):
        frame = object()
        camera = Mock()

        def save_frame(path, selected_frame):
            self.assertIs(selected_frame, frame)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"jpeg")

        camera.save_frame.side_effect = save_frame
        recorder = ObstacleRecorder(self.store, camera)

        record = recorder.record(
            ride_id="ride-1",
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            visual_result=visual_result(frame),
            handling_result=HANDLING_BLOCKED_AND_REPLANNED,
            recovery_status=RECOVERED,
            recovered_point="C3",
        )

        self.assertEqual(record.obstacle_type, "ordinary")
        self.assertEqual(record.detected_color, "red")
        self.assertEqual(record.handling_result, HANDLING_BLOCKED_AND_REPLANNED)
        self.assertEqual(record.recovery_status, RECOVERED)
        self.assertEqual(record.recovered_point, "C3")
        self.assertIsNotNone(record.image_url)
        self.assertIsNone(record.capture_error)
        camera.save_frame.assert_called_once()

    def test_image_failure_still_persists_json_without_disabling_decision(self):
        camera = Mock()
        camera.save_frame.side_effect = CameraCaptureError("write failed")
        recorder = ObstacleRecorder(self.store, camera)

        record = recorder.record(
            ride_id="ride-1",
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            visual_result=visual_result(),
            handling_result=HANDLING_BLOCKED_AND_REPLANNED,
            recovery_status=RECOVERED,
            recovered_point="C3",
        )

        self.assertIsNone(record.image_url)
        self.assertEqual(record.capture_error, "write failed")
        self.assertEqual(len(self.store.list_records()), 1)

    def test_recovery_failure_still_saves_the_pre_recovery_frame(self):
        frame = object()
        camera = Mock()

        def save_frame(path, selected_frame):
            self.assertIs(selected_frame, frame)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"jpeg")

        camera.save_frame.side_effect = save_frame
        recorder = ObstacleRecorder(self.store, camera)

        record = recorder.record(
            ride_id="ride-1",
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            visual_result=visual_result(frame),
            handling_result=HANDLING_RECOVERY_FAILED,
            recovery_status=RECOVERY_FAILED,
            recovered_point=None,
        )

        self.assertEqual(record.handling_result, HANDLING_RECOVERY_FAILED)
        self.assertEqual(record.recovery_status, RECOVERY_FAILED)
        self.assertIsNone(record.recovered_point)
        self.assertIsNotNone(record.image_url)
        camera.save_frame.assert_called_once()


if __name__ == "__main__":
    unittest.main()
