import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.server.obstacle_store import (
    RECOVERED,
    ObstacleStore,
    ObstacleStoreError,
)


class ObstacleStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        self.now = datetime(2026, 7, 14, 6, 32, 18, 123456, tzinfo=timezone.utc)
        self.store = ObstacleStore(self.root, now_fn=lambda: self.now)

    def tearDown(self):
        self.temporary_dir.cleanup()

    def test_saved_record_and_photo_are_reloaded_after_new_store_instance(self):
        record_id, created_at, image_path = self.store.prepare_record("C3", "C4")
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"jpeg")
        saved = self.store.save_record(
            record_id=record_id,
            ride_id="ride-1",
            created_at=created_at,
            from_point="C3",
            to_point="C4",
            distance_cm=13.6,
            recovered_point="C3",
            status=RECOVERED,
            image_filename=image_path.name,
            capture_error=None,
        )

        reloaded = ObstacleStore(self.root).list_records()

        self.assertEqual(reloaded, [saved])
        self.assertEqual(saved.image_url, f"/api/obstacles/{record_id}/image")
        self.assertEqual(ObstacleStore(self.root).get_image_path(record_id), image_path)

    def test_capture_failure_is_saved_without_fake_image(self):
        record_id, created_at, _image_path = self.store.prepare_record("A1", "A2")
        saved = self.store.save_record(
            record_id=record_id,
            ride_id="ride-2",
            created_at=created_at,
            from_point="A1",
            to_point="A2",
            distance_cm=10.0,
            recovered_point="A1",
            status=RECOVERED,
            image_filename=None,
            capture_error="摄像头不可用",
        )

        self.assertIsNone(saved.image_url)
        self.assertEqual(saved.capture_error, "摄像头不可用")
        with self.assertRaises(FileNotFoundError):
            self.store.get_image_path(record_id)

    def test_missing_registered_photo_is_reported_explicitly(self):
        record_id, created_at, image_path = self.store.prepare_record("B2", "B3")
        self.store.save_record(
            record_id=record_id,
            ride_id="ride-3",
            created_at=created_at,
            from_point="B2",
            to_point="B3",
            distance_cm=15.0,
            recovered_point="B2",
            status=RECOVERED,
            image_filename=image_path.name,
            capture_error=None,
        )

        record = self.store.list_records()[0]

        self.assertIsNone(record.image_url)
        self.assertEqual(record.capture_error, "障碍照片文件不存在")

    def test_rejects_unsafe_record_id(self):
        with self.assertRaises(ObstacleStoreError):
            self.store.get_image_path("../secret")


if __name__ == "__main__":
    unittest.main()
