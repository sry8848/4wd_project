import unittest
from unittest.mock import patch

from src.algorithms.color_detect import ColorDetectionResult, ColorRegion
from src.algorithms.qr_detect import QRCodeDecodeDiagnostics
from src.hardware.camera import CameraCaptureError
from src.tasks.obstacle_visual_classification import (
    CLASSIFICATION_FAILED,
    CLASSIFICATION_SUCCESS,
    ERROR_CAMERA_UNAVAILABLE,
    ERROR_CANCELED,
    ERROR_COLOR_CONFLICT,
    ERROR_QR_INVALID_PAYLOAD,
    ERROR_QR_TIMEOUT,
    OBSTACLE_TYPE_ORDINARY,
    OBSTACLE_TYPE_TOLL,
    VISUAL_PHASE_SCANNING_TOLL_QR,
    ObstacleVisualClassificationTask,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class FakeCamera:
    def __init__(self, frames, clock):
        self.frames = list(frames)
        self.clock = clock
        self.read_count = 0
        self.close_count = 0

    def read_frame(self):
        self.read_count += 1
        self.clock.now += 1.0
        if not self.frames:
            return f"frame-{self.read_count}"
        value = self.frames.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.close_count += 1


class FakeColorDetector:
    def __init__(self, colors_by_frame):
        self.colors_by_frame = colors_by_frame

    def detect(self, frame):
        colors = self.colors_by_frame.get(frame, ())
        regions = tuple(
            ColorRegion(color, 2000.0 - index, 0.1, (10, 10), (0, 0, 20, 20))
            for index, color in enumerate(colors)
        )
        return ColorDetectionResult(640, 480, regions)


class FakeQRRecognizer:
    def __init__(self, results=None, error=None):
        self.results = list(results or [])
        self.error = error
        self.calls = []

    def decode_with_diagnostics(self, frame):
        self.calls.append(frame)
        if self.error is not None:
            raise self.error
        if self.results:
            return self.results.pop(0)
        return QRCodeDecodeDiagnostics((), False)


class ObstacleVisualClassificationTaskTest(unittest.TestCase):
    def build_task(self, frames, colors, qr_results=None, **kwargs):
        self.clock = FakeClock()
        self.camera = FakeCamera(frames, self.clock)
        self.qr = FakeQRRecognizer(qr_results)
        return ObstacleVisualClassificationTask(
            FakeColorDetector(colors),
            self.qr,
            self.camera,
            color_confirm_frames=3,
            color_timeout_seconds=kwargs.get("color_timeout_seconds", 8.0),
            qr_timeout_seconds=kwargs.get("qr_timeout_seconds", 4.0),
            monotonic_fn=self.clock.monotonic,
        )

    def test_three_red_frames_finish_without_qr_scan(self):
        task = self.build_task(
            ["r1", "r2", "r3"],
            {"r1": ("red",), "r2": ("red",), "r3": ("red",)},
        )

        result = task.classify()

        self.assertEqual(result.obstacle_type, OBSTACLE_TYPE_ORDINARY)
        self.assertEqual(result.detected_color, "red")
        self.assertEqual(result.classification_status, CLASSIFICATION_SUCCESS)
        self.assertEqual(result.record_frame, "r3")
        self.assertEqual(self.qr.calls, [])
        self.assertEqual(self.camera.close_count, 1)

    def test_alternating_colors_reset_the_confirmation_streak(self):
        frames = ["r1", "b1", "r2", "r3", "r4"]
        task = self.build_task(
            frames,
            {
                "r1": ("red",),
                "b1": ("blue",),
                "r2": ("red",),
                "r3": ("red",),
                "r4": ("red",),
            },
        )

        result = task.classify()

        self.assertEqual(result.record_frame, "r4")
        self.assertEqual(self.camera.read_count, 5)

    def test_red_blue_conflict_times_out_as_failed_without_fake_color(self):
        task = self.build_task(
            ["c1", "c2", "c3"],
            {"c1": ("red", "blue"), "c2": (), "c3": ()},
            color_timeout_seconds=3.0,
        )

        result = task.classify()

        self.assertEqual(result.classification_status, CLASSIFICATION_FAILED)
        self.assertIsNone(result.detected_color)
        self.assertEqual(result.recognition_error, ERROR_COLOR_CONFLICT)
        self.assertEqual(result.record_frame, "c1")

    def test_blue_then_strict_toll_qr_returns_toll_and_reports_phase(self):
        phases = []
        task = self.build_task(
            ["b1", "b2", "b3", "q1", "q2"],
            {"b1": ("blue",), "b2": ("blue",), "b3": ("blue",)},
            [
                QRCodeDecodeDiagnostics(("toll:gate1",), True),
                QRCodeDecodeDiagnostics(("TOLL:GATE1",), True),
            ],
        )

        result = task.classify(phase_changed_fn=phases.append)

        self.assertEqual(phases, [VISUAL_PHASE_SCANNING_TOLL_QR])
        self.assertEqual(result.obstacle_type, OBSTACLE_TYPE_TOLL)
        self.assertEqual(result.station_id, "GATE1")
        self.assertEqual(result.record_frame, "q2")

    def test_only_invalid_qr_payloads_fail_as_safe_ordinary_obstacle(self):
        task = self.build_task(
            ["b1", "b2", "b3", "q1", "q2", "q3", "q4"],
            {"b1": ("blue",), "b2": ("blue",), "b3": ("blue",)},
            [
                QRCodeDecodeDiagnostics(("toll:gate1", "PAY:GATE1"), True),
                QRCodeDecodeDiagnostics(("TOLL:",), True),
                QRCodeDecodeDiagnostics(("TOLL: GATE1",), True),
            ],
            qr_timeout_seconds=3.0,
        )

        result = task.classify()

        self.assertEqual(result.obstacle_type, OBSTACLE_TYPE_ORDINARY)
        self.assertEqual(result.detected_color, "blue")
        self.assertEqual(result.classification_status, CLASSIFICATION_FAILED)
        self.assertEqual(result.recognition_error, ERROR_QR_INVALID_PAYLOAD)

    def test_qr_timeout_records_last_qr_phase_frame(self):
        task = self.build_task(
            ["b1", "b2", "b3", "q1", "q2"],
            {"b1": ("blue",), "b2": ("blue",), "b3": ("blue",)},
            [
                QRCodeDecodeDiagnostics((), False),
                QRCodeDecodeDiagnostics((), False),
            ],
            qr_timeout_seconds=2.0,
        )

        result = task.classify()

        self.assertEqual(result.recognition_error, ERROR_QR_TIMEOUT)
        self.assertEqual(result.record_frame, "q2")

    def test_cancel_and_camera_failure_return_explicit_safe_failures(self):
        task = self.build_task(["r1"], {"r1": ("red",)})
        canceled = task.classify(cancel_requested_fn=lambda: True)
        self.assertEqual(canceled.recognition_error, ERROR_CANCELED)
        self.assertEqual(self.camera.read_count, 0)
        self.assertEqual(self.camera.close_count, 1)

        task = self.build_task(
            [CameraCaptureError("offline") for _index in range(3)],
            {},
            color_timeout_seconds=3.0,
        )
        with patch("src.tasks.obstacle_visual_classification.time.sleep"):
            failed = task.classify()
        self.assertEqual(failed.recognition_error, ERROR_CAMERA_UNAVAILABLE)
        self.assertIsNone(failed.record_frame)
        self.assertEqual(self.camera.close_count, 1)

    def test_color_scan_recovers_after_transient_camera_failure(self):
        task = self.build_task(
            [CameraCaptureError("offline"), "r1", "r2", "r3"],
            {"r1": ("red",), "r2": ("red",), "r3": ("red",)},
        )

        with patch("src.tasks.obstacle_visual_classification.time.sleep") as sleep:
            result = task.classify()

        self.assertEqual(result.classification_status, CLASSIFICATION_SUCCESS)
        self.assertEqual(result.detected_color, "red")
        sleep.assert_called_once_with(0.1)
        self.assertEqual(self.camera.close_count, 1)

    def test_qr_scan_recovers_after_transient_camera_failure(self):
        task = self.build_task(
            [
                "b1",
                "b2",
                "b3",
                CameraCaptureError("offline"),
                "q1",
            ],
            {"b1": ("blue",), "b2": ("blue",), "b3": ("blue",)},
            [QRCodeDecodeDiagnostics(("TOLL:GATE1",), True)],
        )

        with patch("src.tasks.obstacle_visual_classification.time.sleep") as sleep:
            result = task.classify()

        self.assertEqual(result.obstacle_type, OBSTACLE_TYPE_TOLL)
        self.assertEqual(result.station_id, "GATE1")
        sleep.assert_called_once_with(0.1)
        self.assertEqual(self.camera.close_count, 1)


if __name__ == "__main__":
    unittest.main()
