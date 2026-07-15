import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.hardware.camera import CameraCaptureError
from src.tasks.face_verification import (
    FACE_CANCELED,
    FACE_MATCHED,
    FACE_TIMEOUT,
    FaceVerificationTask,
)


class StepClock:
    def __init__(self, step=0.01):
        self.value = -step
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


class FaceVerificationTaskTest(unittest.TestCase):
    def make_task(self, match_sequences, *, timeout=1.0, step=0.01):
        recognizer = Mock()
        recognizer.labels = ("Alice", "Bob")
        recognizer.recognize.side_effect = match_sequences
        camera = Mock()
        camera.read_frame.side_effect = [
            f"frame-{index}" for index in range(len(match_sequences))
        ]
        task = FaceVerificationTask(
            recognizer,
            camera,
            confirm_frames=3,
            timeout_seconds=timeout,
            monotonic_fn=StepClock(step),
        )
        return task, recognizer, camera

    def test_expected_passenger_requires_three_consecutive_frames(self):
        alice = SimpleNamespace(label="Alice", distance=0.1)
        bob = SimpleNamespace(label="Bob", distance=0.08)
        task, recognizer, camera = self.make_task(
            [[alice], [alice], [bob], [alice], [alice], [alice]]
        )

        result = task.verify("Alice")

        self.assertEqual(result.outcome, FACE_MATCHED)
        self.assertEqual(result.detected_passenger_id, "Alice")
        self.assertEqual(result.frame, "frame-5")
        self.assertEqual(recognizer.recognize.call_count, 6)
        self.assertEqual(camera.read_frame.call_count, 6)
        camera.close.assert_called_once_with()

    def test_timeout_keeps_closest_face_frame(self):
        bob_far = SimpleNamespace(label="Bob", distance=0.28)
        unknown_close = SimpleNamespace(label=None, distance=0.22)
        task, _recognizer, _camera = self.make_task(
            [[bob_far], [unknown_close]],
            timeout=0.25,
            step=0.1,
        )

        result = task.verify("Alice")

        self.assertEqual(result.outcome, FACE_TIMEOUT)
        self.assertIsNone(result.detected_passenger_id)
        self.assertEqual(result.distance, 0.22)
        self.assertEqual(result.frame, "frame-1")

    def test_timeout_without_face_keeps_last_frame(self):
        task, _recognizer, _camera = self.make_task(
            [[], []],
            timeout=0.25,
            step=0.1,
        )

        result = task.verify("Alice")

        self.assertEqual(result.outcome, FACE_TIMEOUT)
        self.assertIsNone(result.distance)
        self.assertEqual(result.frame, "frame-1")

    def test_cancel_stops_before_reading_another_frame(self):
        task, recognizer, camera = self.make_task([[]])

        result = task.verify("Alice", cancel_requested_fn=lambda: True)

        self.assertEqual(result.outcome, FACE_CANCELED)
        camera.read_frame.assert_not_called()
        recognizer.recognize.assert_not_called()
        camera.close.assert_called_once_with()

    def test_transient_camera_failure_recovers_within_same_attempt(self):
        alice = SimpleNamespace(label="Alice", distance=0.1)
        recognizer = Mock()
        recognizer.labels = ("Alice",)
        recognizer.recognize.side_effect = [[alice], [alice], [alice]]
        camera = Mock()
        camera.read_frame.side_effect = [
            CameraCaptureError("temporary disconnect"),
            "frame-1",
            "frame-2",
            "frame-3",
        ]
        task = FaceVerificationTask(
            recognizer,
            camera,
            confirm_frames=3,
            timeout_seconds=1.0,
            monotonic_fn=StepClock(0.01),
        )

        with patch("src.tasks.face_verification.time.sleep") as sleep:
            result = task.verify("Alice")

        self.assertEqual(result.outcome, FACE_MATCHED)
        self.assertEqual(result.frame, "frame-3")
        sleep.assert_called_once_with(0.1)
        camera.close.assert_called_once_with()

    def test_camera_failures_continue_only_until_existing_timeout(self):
        recognizer = Mock()
        recognizer.labels = ("Alice",)
        camera = Mock()
        camera.read_frame.side_effect = CameraCaptureError("offline")
        task = FaceVerificationTask(
            recognizer,
            camera,
            timeout_seconds=0.25,
            monotonic_fn=StepClock(0.1),
        )

        with patch("src.tasks.face_verification.time.sleep") as sleep:
            result = task.verify("Alice")

        self.assertEqual(result.outcome, FACE_TIMEOUT)
        self.assertIsNone(result.frame)
        self.assertGreaterEqual(camera.read_frame.call_count, 1)
        self.assertLessEqual(camera.read_frame.call_count, 3)
        self.assertEqual(sleep.call_count, camera.read_frame.call_count)
        recognizer.recognize.assert_not_called()
        camera.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
