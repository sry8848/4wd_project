import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.server.obstacle_store import (
    HANDLING_BLOCKED_AND_REPLANNED,
    HANDLING_CONTINUED_CURRENT_EDGE,
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
            obstacle_type="ordinary",
            detected_color="red",
            classification_status="success",
            station_id=None,
            recognition_error=None,
            handling_result=HANDLING_BLOCKED_AND_REPLANNED,
            recovery_status=RECOVERED,
            recovered_point="C3",
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
            obstacle_type="ordinary",
            detected_color=None,
            classification_status="failed",
            station_id=None,
            recognition_error="color_timeout",
            handling_result=HANDLING_BLOCKED_AND_REPLANNED,
            recovery_status=RECOVERED,
            recovered_point="A1",
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
            obstacle_type="ordinary",
            detected_color="red",
            classification_status="success",
            station_id=None,
            recognition_error=None,
            handling_result=HANDLING_BLOCKED_AND_REPLANNED,
            recovery_status=RECOVERED,
            recovered_point="B2",
            image_filename=image_path.name,
            capture_error=None,
        )

        record = self.store.list_records()[0]

        self.assertIsNone(record.image_url)
        self.assertEqual(record.capture_error, "障碍照片文件不存在")

    def test_rejects_unsafe_record_id(self):
        with self.assertRaises(ObstacleStoreError):
            self.store.get_image_path("../secret")

    def test_toll_record_can_continue_without_fake_recovery(self):
        record_id, created_at, image_path = self.store.prepare_record("C3", "C4")
        image_path.write_bytes(b"jpeg")

        saved = self.store.save_record(
            record_id=record_id,
            ride_id="ride-toll",
            created_at=created_at,
            from_point="C3",
            to_point="C4",
            distance_cm=12.0,
            obstacle_type="toll",
            detected_color="blue",
            classification_status="success",
            station_id="GATE1",
            recognition_error=None,
            handling_result=HANDLING_CONTINUED_CURRENT_EDGE,
            recovery_status=None,
            recovered_point=None,
            image_filename=image_path.name,
            capture_error=None,
        )

        self.assertEqual(saved.handling_result, HANDLING_CONTINUED_CURRENT_EDGE)
        self.assertIsNone(saved.recovery_status)
        self.assertIsNone(saved.recovered_point)

    def test_rejects_legacy_record_instead_of_guessing_missing_visual_facts(self):
        record_id, created_at, _image_path = self.store.prepare_record("A1", "A2")
        legacy_path = self.root / f"{record_id}.json"
        legacy_path.write_text(
            json.dumps(
                {
                    "id": record_id,
                    "ride_id": "ride-old",
                    "created_at": created_at,
                    "from_point": "A1",
                    "to_point": "A2",
                    "distance_cm": 12.0,
                    "status": "recovered",
                    "recovered_point": "A1",
                    "image_filename": None,
                    "capture_error": "旧记录没有照片",
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ObstacleStoreError, "字段不符合契约"):
            self.store.list_records()

    def test_rejects_ordinary_obstacle_claiming_toll_continue_action(self):
        record_id, created_at, _image_path = self.store.prepare_record("B1", "B2")

        with self.assertRaisesRegex(ObstacleStoreError, "处理与恢复字段"):
            self.store.save_record(
                record_id=record_id,
                ride_id="ride-invalid",
                created_at=created_at,
                from_point="B1",
                to_point="B2",
                distance_cm=14.0,
                obstacle_type="ordinary",
                detected_color="red",
                classification_status="success",
                station_id=None,
                recognition_error=None,
                handling_result=HANDLING_CONTINUED_CURRENT_EDGE,
                recovery_status=None,
                recovered_point=None,
                image_filename=None,
                capture_error="没有照片",
            )


if __name__ == "__main__":
    unittest.main()
