import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.hardware.camera import CameraCaptureError
from src.server.face_verification_store import (
    FaceVerificationRecorder,
    FaceVerificationStore,
    FaceVerificationStoreError,
)
from src.tasks.face_verification import FACE_MATCHED, FaceVerificationResult


FIXED_TIME = datetime(2026, 7, 14, 10, 0, 0, 123456, tzinfo=timezone.utc)
RECORD_ID = "face_20260714_100000_123456"


class FakeCamera:
    def __init__(self, error=None):
        self.error = error

    def save_frame(self, path, _frame):
        if self.error is not None:
            raise CameraCaptureError(self.error)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"jpeg")
        return Path(path)


class FaceVerificationStoreTest(unittest.TestCase):
    def result(self):
        return FaceVerificationResult(FACE_MATCHED, "Alice", 0.12, object())

    def test_recorder_saves_exact_json_and_registered_image(self):
        with TemporaryDirectory() as temp_dir:
            store = FaceVerificationStore(temp_dir, now_fn=lambda: FIXED_TIME)
            record = FaceVerificationRecorder(store, FakeCamera()).record(
                ride_id="ride-1",
                passenger_id="Alice",
                verification_result=self.result(),
            )

            self.assertEqual(record.id, RECORD_ID)
            self.assertEqual(record.result, FACE_MATCHED)
            self.assertEqual(
                record.image_url,
                f"/api/face-verifications/{RECORD_ID}/image",
            )
            self.assertEqual(store.get_image_path(RECORD_ID).read_bytes(), b"jpeg")
            payload = json.loads(
                (Path(temp_dir) / f"{RECORD_ID}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["passenger_id"], "Alice")
            self.assertEqual(payload["image_filename"], f"{RECORD_ID}.jpg")

    def test_image_failure_keeps_json_and_null_image_url(self):
        with TemporaryDirectory() as temp_dir:
            store = FaceVerificationStore(temp_dir, now_fn=lambda: FIXED_TIME)
            record = FaceVerificationRecorder(
                store,
                FakeCamera("disk full"),
            ).record(
                ride_id="ride-1",
                passenger_id="Alice",
                verification_result=self.result(),
            )

            self.assertIsNone(record.image_url)
            self.assertEqual(record.image_error, "disk full")
            with self.assertRaises(FileNotFoundError):
                store.get_image_path(RECORD_ID)

    def test_json_write_failure_is_reported(self):
        with TemporaryDirectory() as temp_dir:
            root_file = Path(temp_dir) / "not-a-directory"
            root_file.write_text("occupied", encoding="utf-8")
            store = FaceVerificationStore(root_file, now_fn=lambda: FIXED_TIME)

            with self.assertRaises(FaceVerificationStoreError):
                FaceVerificationRecorder(store, FakeCamera("no image")).record(
                    ride_id="ride-1",
                    passenger_id="Alice",
                    verification_result=self.result(),
                )

    def test_invalid_id_and_extra_json_field_are_rejected(self):
        with TemporaryDirectory() as temp_dir:
            store = FaceVerificationStore(temp_dir, now_fn=lambda: FIXED_TIME)
            with self.assertRaises(FaceVerificationStoreError):
                store.get_image_path("../secret")

            payload = {
                "id": RECORD_ID,
                "ride_id": "ride-1",
                "passenger_id": "Alice",
                "detected_passenger_id": "Alice",
                "result": FACE_MATCHED,
                "distance": 0.12,
                "created_at": FIXED_TIME.isoformat(),
                "image_filename": f"{RECORD_ID}.jpg",
                "image_error": None,
                "extra": True,
            }
            (Path(temp_dir) / f"{RECORD_ID}.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with self.assertRaises(FaceVerificationStoreError):
                store.get_image_path(RECORD_ID)


if __name__ == "__main__":
    unittest.main()
