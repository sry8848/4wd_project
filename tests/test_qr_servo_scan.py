import unittest

from src.tasks.qr_servo_scan import QRCodeServoScanner


class FakeCamera:
    def __init__(self, frames):
        self.frames = list(frames)

    def read_frame(self, **_kwargs):
        return self.frames.pop(0)


class FakeServo:
    def __init__(self):
        self.angles = []

    def move_to(self, angle):
        self.angles.append(angle)


class FakeRecognizer:
    def __init__(self, decoded_per_frame):
        self.decoded_per_frame = list(decoded_per_frame)

    def decode(self, _frame):
        return self.decoded_per_frame.pop(0)


class QRCodeServoScannerDiagnosticsTest(unittest.TestCase):
    def build_scanner(self, frames, decoded_per_frame):
        camera = FakeCamera(frames)
        pan_servo = FakeServo()
        tilt_servo = FakeServo()
        scanner = QRCodeServoScanner(
            camera,
            pan_servo,
            tilt_servo,
            FakeRecognizer(decoded_per_frame),
            time_fn=lambda: 0.0,
        )
        return scanner

    def test_failed_scan_returns_last_frame_for_timeout_snapshot(self):
        first_frame = object()
        last_frame = object()
        scanner = self.build_scanner(
            [first_frame, last_frame],
            [[], []],
        )

        result = scanner.scan(
            pan_angles=[90],
            tilt_angles=[90],
            frames_per_position=2,
            discard_frames_after_move=0,
            timeout_seconds=10,
        )

        self.assertIsNone(result.payload)
        self.assertEqual(result.frames_scanned, 2)
        self.assertIs(result.last_frame, last_frame)

    def test_successful_scan_returns_exact_decoded_frame(self):
        first_frame = object()
        decoded_frame = object()
        scanner = self.build_scanner(
            [first_frame, decoded_frame],
            [[], ["TOLL:GATE1"]],
        )

        result = scanner.scan(
            pan_angles=[90],
            tilt_angles=[90],
            frames_per_position=2,
            discard_frames_after_move=0,
            timeout_seconds=10,
        )

        self.assertEqual(result.payload.raw_text, "TOLL:GATE1")
        self.assertEqual(result.frames_scanned, 2)
        self.assertIs(result.last_frame, decoded_frame)


if __name__ == "__main__":
    unittest.main()
