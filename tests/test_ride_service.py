import unittest
from threading import Thread
import time
from types import SimpleNamespace
from unittest.mock import Mock

from src.server.ride_service import RideService
from src.server.runtime_state import RuntimeState
from src.server.schemas import RideCreateRequest
from src.tasks.face_verification import FACE_MATCHED, FaceVerificationResult
from src.tasks.face_verification import FACE_TIMEOUT
from src.tasks.grid_navigation import NAV_ARRIVED, NAV_CANCELED, NAV_NO_PATH


class FakeNavigator:
    """同步回放可信节点，模拟 GridNavigator 的公开回调契约。"""

    def __init__(self, segment_nodes, results=None, after_node_fn=None):
        self.segment_nodes = [list(nodes) for nodes in segment_nodes]
        self.results = list(results or [])
        self.after_node_fn = after_node_fn
        self.calls = []

    def navigate(
        self,
        start,
        end,
        initial_heading,
        cancel_requested_fn=None,
        node_reached_fn=None,
        stop_at_next_node_fn=None,
        obstacle_result_fn=None,
    ):
        self.calls.append((start, end, initial_heading))
        nodes = self.segment_nodes.pop(0) if self.segment_nodes else []
        for node, heading in nodes:
            node_reached_fn(node, heading)
            if self.after_node_fn is not None:
                self.after_node_fn()
            if stop_at_next_node_fn is not None and stop_at_next_node_fn():
                return NAV_CANCELED
            if cancel_requested_fn is not None and cancel_requested_fn():
                return NAV_CANCELED
        return self.results.pop(0) if self.results else NAV_ARRIVED


class RideServiceHardwareRideTest(unittest.TestCase):
    def setUp(self):
        self.state = RuntimeState()
        self.mail_notifier = Mock()
        self.service = RideService(self.state, self.mail_notifier)
        self.obstacle_recorder = Mock()
        self.face_verifier = Mock()
        self.face_verifier.verify.return_value = FaceVerificationResult(
            FACE_MATCHED,
            "Alice",
            0.1,
            object(),
        )
        self.face_recorder = Mock()
        self.face_recorder.record.return_value = SimpleNamespace(
            id="face_20260714_100000_123456",
            image_url="/api/face-verifications/face_20260714_100000_123456/image",
            image_error=None,
        )

    def submit(self, start="A1", waypoints=None, end="E5"):
        request = RideCreateRequest.from_payload(
            {
                "passenger_id": "Alice",
                "start": start,
                "waypoints": waypoints or [],
                "end": end,
            }
        )
        return self.service.submit_ride(request)

    def run_ride(self, ride_id, navigator, *, auto_confirm=True):
        """在线程中执行真实等待流程，并在需要时模拟前端确认上车。"""

        outcome = {}

        def target():
            outcome["ride"] = self.service.run_hardware_ride(
                ride_id,
                navigator,
                self.obstacle_recorder,
                self.face_verifier,
                self.face_recorder,
            )

        thread = Thread(target=target)
        thread.start()
        deadline = time.monotonic() + 2.0
        confirmed = False
        while thread.is_alive() and time.monotonic() < deadline:
            ride = self.state.get_ride(ride_id)
            if (
                auto_confirm
                and not confirmed
                and ride.status == "awaiting_boarding_confirmation"
            ):
                self.service.confirm_boarding(ride_id)
                confirmed = True
            time.sleep(0.005)
        thread.join(timeout=0.2)
        self.assertFalse(thread.is_alive(), "行程测试线程未按预期结束")
        return outcome["ride"]

    def wait_for_status(self, ride_id, expected_status):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            ride = self.state.get_ride(ride_id)
            if ride.status == expected_status:
                return ride
            time.sleep(0.005)
        self.fail(f"行程未进入状态 {expected_status}")

    def start_ride_thread(self, ride_id, navigator):
        outcome = {}

        def target():
            outcome["ride"] = self.service.run_hardware_ride(
                ride_id,
                navigator,
                self.obstacle_recorder,
                self.face_verifier,
                self.face_recorder,
            )

        thread = Thread(target=target)
        thread.start()
        return thread, outcome

    def test_pickup_does_not_start_next_segment_before_boarding_confirmation(self):
        ride = self.submit(start="C3", end="C4")
        navigator = FakeNavigator([[((2, 3), "east")]])
        thread, outcome = self.start_ride_thread(ride.id, navigator)

        waiting = self.wait_for_status(ride.id, "awaiting_boarding_confirmation")
        self.assertEqual(waiting.current_position, "C3")
        self.assertEqual(navigator.calls, [])
        time.sleep(0.03)
        self.assertEqual(navigator.calls, [])

        self.service.confirm_boarding(ride.id)
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["ride"].status, "arrived")
        self.assertEqual(len(navigator.calls), 1)

    def test_timeout_retries_same_ride_then_waits_for_confirmation(self):
        ride = self.submit(start="C3", end="C4")
        self.face_verifier.verify.side_effect = [
            FaceVerificationResult(FACE_TIMEOUT, "Bob", 0.2, object()),
            FaceVerificationResult(FACE_MATCHED, "Alice", 0.1, object()),
        ]
        navigator = FakeNavigator([[((2, 3), "east")]])
        thread, outcome = self.start_ride_thread(ride.id, navigator)

        self.wait_for_status(ride.id, "waiting_passenger_retry")
        retrying = self.service.request_face_verification_retry(ride.id)
        self.assertEqual(retrying.id, ride.id)
        self.assertEqual(retrying.status, "verifying_passenger")
        self.wait_for_status(ride.id, "awaiting_boarding_confirmation")
        self.service.confirm_boarding(ride.id)

        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["ride"].status, "arrived")
        self.assertEqual(self.face_verifier.verify.call_count, 2)

    def test_cancel_while_waiting_at_pickup_finishes_without_navigation(self):
        ride = self.submit(start="C3", end="C4")
        self.face_verifier.verify.return_value = FaceVerificationResult(
            FACE_TIMEOUT,
            None,
            None,
            object(),
        )
        navigator = FakeNavigator([[((2, 3), "east")]])
        thread, outcome = self.start_ride_thread(ride.id, navigator)

        self.wait_for_status(ride.id, "waiting_passenger_retry")
        canceled = self.service.request_cancel_ride(ride.id)

        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(canceled.status, "canceled")
        self.assertEqual(outcome["ride"].status, "canceled")
        self.assertEqual(navigator.calls, [])

    def test_retry_and_confirm_reject_wrong_states(self):
        ride = self.submit()

        with self.assertRaisesRegex(Exception, "不在等待重新识别"):
            self.service.request_face_verification_retry(ride.id)
        with self.assertRaisesRegex(Exception, "不在等待确认上车"):
            self.service.confirm_boarding(ride.id)

    def test_hardware_ride_executes_each_stop_and_records_trusted_pose(self):
        ride = self.submit(waypoints=["C2"])
        navigator = FakeNavigator(
            [
                [
                    ((1, 2), "north"),
                    ((0, 2), "north"),
                    ((0, 1), "west"),
                    ((0, 0), "west"),
                ],
                [
                    ((0, 1), "east"),
                    ((1, 1), "south"),
                    ((2, 1), "south"),
                ],
                [
                    ((2, 2), "east"),
                    ((2, 3), "east"),
                    ((2, 4), "east"),
                    ((3, 4), "south"),
                    ((4, 4), "south"),
                ],
            ]
        )

        finished = self.run_ride(ride.id, navigator)

        self.assertEqual(finished.status, "arrived")
        self.assertEqual(
            navigator.calls,
            [
                ((2, 2), (0, 0), "north"),
                ((0, 0), (2, 1), "west"),
                ((2, 1), (4, 4), "south"),
            ],
        )
        self.assertEqual(
            finished.progress,
            [
                "C3",
                "B3",
                "A3",
                "A2",
                "A1",
                "A2",
                "B2",
                "C2",
                "C3",
                "C4",
                "C5",
                "D5",
                "E5",
            ],
        )
        self.assertEqual(finished.route, finished.progress)
        self.assertEqual(self.mail_notifier.notify.call_count, 3)
        subjects = [call.args[0] for call in self.mail_notifier.notify.call_args_list]
        self.assertEqual(
            subjects,
            [
                "4WD 小车到达起点：A1",
                "4WD 小车到达途径点：C2",
                "4WD 小车到达终点：E5",
            ],
        )
        self.assertIn(
            "完整路线：A1 → C2 → E5",
            self.mail_notifier.notify.call_args_list[1].args[1],
        )
        self.assertEqual(self.state.get_car_status().heading, "south")

    def test_hardware_ride_stops_updating_after_cancel(self):
        ride = self.submit()
        canceled = False

        def cancel_once():
            nonlocal canceled
            if not canceled:
                canceled = True
                self.service.request_cancel_ride(ride.id)

        navigator = FakeNavigator(
            [[((1, 2), "north"), ((0, 2), "north")]],
            after_node_fn=cancel_once,
        )

        finished = self.run_ride(ride.id, navigator)

        self.assertEqual(finished.status, "canceled")
        self.assertEqual(finished.progress, ["C3", "B3"])
        self.assertEqual(finished.route, finished.progress)
        self.assertEqual(finished.current_position, "B3")
        self.assertIn("节点 B3 停车", finished.eta_text)
        self.assertEqual(len(navigator.calls), 1)
        self.mail_notifier.notify.assert_not_called()

    def test_cancel_requested_before_segment_still_moves_to_next_forward_node(self):
        ride = self.submit()
        requested = self.service.request_cancel_ride(ride.id)
        self.assertEqual(requested.status, "canceling")
        self.assertIsNotNone(self.state.get_active_ride())

        navigator = FakeNavigator(
            [[((1, 2), "north"), ((0, 2), "north")]],
        )

        finished = self.run_ride(ride.id, navigator)

        self.assertEqual(finished.status, "canceled")
        self.assertEqual(finished.progress, ["C3", "B3"])
        self.assertEqual(finished.route, finished.progress)
        self.assertEqual(finished.current_position, "B3")
        self.assertIsNone(self.state.get_active_ride())

    def test_hardware_ride_marks_no_path_as_failed(self):
        ride = self.submit()
        navigator = FakeNavigator([[]], results=[NAV_NO_PATH])

        finished = self.run_ride(ride.id, navigator)

        self.assertEqual(finished.status, "failed")
        self.assertIn("无法规划到点位 A1", finished.error_message)
        self.assertEqual(finished.current_position, "C3")
        self.mail_notifier.notify.assert_not_called()

    def test_mail_failure_adds_system_event_without_failing_arrived_ride(self):
        ride = self.submit(start="C3", end="C4")
        navigator = FakeNavigator([[((2, 3), "east")]])

        finished = self.run_ride(ride.id, navigator)
        result_callbacks = [
            call.args[2] for call in self.mail_notifier.notify.call_args_list
        ]
        result_callbacks[-1](RuntimeError("SMTP rejected"))

        self.assertEqual(finished.status, "arrived")
        self.assertEqual(self.state.get_ride(ride.id).status, "arrived")
        events, _next_after = self.state.list_ride_events(ride.id)
        self.assertTrue(
            any(
                event.type == "system" and "SMTP rejected" in event.text
                for event in events
            )
        )

    def test_obstacle_callback_persists_record_and_publishes_event(self):
        ride = self.submit(start="C4", end="C5")
        record = SimpleNamespace(
            id="obstacle_20260714_083000_123456_C3_C4",
            distance_cm=12.5,
            status="recovered",
        )
        self.obstacle_recorder.record.return_value = record

        class ObstacleNavigator(FakeNavigator):
            def navigate(self, *args, **kwargs):
                if not hasattr(self, "obstacle_reported"):
                    self.obstacle_reported = True
                    kwargs["obstacle_result_fn"](
                        (2, 2),
                        (2, 3),
                        12.5,
                        "recovered_to_start_node",
                        "east",
                    )
                return NAV_ARRIVED

        finished = self.run_ride(ride.id, ObstacleNavigator([[], []]))

        self.assertEqual(finished.status, "arrived")
        self.obstacle_recorder.record.assert_called_once_with(
            ride_id=ride.id,
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            recovery_status="recovered_to_start_node",
        )
        events, _next_after = self.state.list_ride_events(ride.id)
        obstacle_event = [event for event in events if event.type == "obstacle"][0]
        self.assertEqual(obstacle_event.obstacle_id, record.id)
        self.assertIn("12.5 cm", obstacle_event.text)


if __name__ == "__main__":
    unittest.main()
