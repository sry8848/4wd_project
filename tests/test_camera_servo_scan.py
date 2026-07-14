import unittest

from src.tasks.camera_servo_scan import CameraServoScanner


class FakeCamera:
    def __init__(self, frames):
        self.frames = list(frames)
        self.read_calls = []

    def read_frame(self, **kwargs):
        self.read_calls.append(kwargs)
        return self.frames.pop(0)


class FakeServo:
    def __init__(self):
        self.angles = []

    def move_to(self, angle):
        self.angles.append(angle)


class CameraServoScannerTest(unittest.TestCase):
    def build_scanner(self, frames):
        camera = FakeCamera(frames)
        pan_servo = FakeServo()
        tilt_servo = FakeServo()
        scanner = CameraServoScanner(
            camera,
            pan_servo,
            tilt_servo,
            time_fn=lambda: 0.0,
        )
        return scanner, camera, pan_servo, tilt_servo

    def test_scans_tilt_outer_and_pan_inner(self):
        scanner, _camera, pan_servo, tilt_servo = self.build_scanner(
            [object(), object(), object(), object()]
        )
        visited = []

        result = scanner.scan(
            lambda item: visited.append((item.pan_angle, item.tilt_angle)),
            pan_angles=[90, 70],
            tilt_angles=[90, 75],
            frames_per_position=1,
            discard_frames_after_move=0,
            timeout_seconds=10,
        )

        self.assertEqual(tilt_servo.angles, [90.0, 75.0])
        self.assertEqual(pan_servo.angles, [90.0, 70.0, 90.0, 70.0])
        self.assertEqual(
            visited,
            [(90.0, 90.0), (70.0, 90.0), (90.0, 75.0), (70.0, 75.0)],
        )
        self.assertEqual(result.positions_scanned, 4)
        self.assertEqual(result.frames_scanned, 4)
        self.assertIsNone(result.value)

    def test_stops_at_first_handler_result_and_reports_direction(self):
        scanner, _camera, pan_servo, tilt_servo = self.build_scanner(
            [object(), object(), object()]
        )

        def handler(item):
            if item.pan_angle == 70:
                return "found"
            return None

        result = scanner.scan(
            handler,
            pan_angles=[90, 70, 110],
            tilt_angles=[90, 75],
            frames_per_position=1,
            discard_frames_after_move=0,
            timeout_seconds=10,
        )

        self.assertEqual(result.value, "found")
        self.assertEqual(result.pan_angle, 70.0)
        self.assertEqual(result.tilt_angle, 90.0)
        self.assertEqual(result.positions_scanned, 2)
        self.assertEqual(pan_servo.angles, [90.0, 70.0])
        self.assertEqual(tilt_servo.angles, [90.0])

    def test_discards_buffered_frames_before_feature_callback(self):
        discarded = object()
        analyzed = object()
        scanner, camera, _pan_servo, _tilt_servo = self.build_scanner(
            [discarded, analyzed]
        )
        received = []

        result = scanner.scan(
            lambda item: received.append(item.frame),
            pan_angles=[90],
            tilt_angles=[90],
            frames_per_position=1,
            discard_frames_after_move=3,
            timeout_seconds=10,
        )

        self.assertEqual(received, [analyzed])
        self.assertEqual(
            camera.read_calls,
            [{"warmup_frames": 2, "copy": False}, {"copy": False}],
        )
        self.assertIs(result.last_frame, analyzed)


if __name__ == "__main__":
    unittest.main()
