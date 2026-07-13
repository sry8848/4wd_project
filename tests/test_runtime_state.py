import unittest

from src.server.point_codec import PointValidationError
from src.server.runtime_state import RuntimeState, RuntimeStateError
from src.server.schemas import RideCreateRequest


class RuntimeStateTest(unittest.TestCase):
    def setUp(self):
        self.times = iter(
            [
                "2026-07-09T15:30:00+08:00",
                "2026-07-09T15:30:01+08:00",
                "2026-07-09T15:30:02+08:00",
                "2026-07-09T15:30:03+08:00",
                "2026-07-09T15:30:04+08:00",
                "2026-07-09T15:30:05+08:00",
            ]
        )
        self.state = RuntimeState(now_fn=lambda: next(self.times))

    def test_initial_car_status_is_idle_at_default_position(self):
        status = self.state.get_car_status()

        self.assertEqual(status.mode, "idle")
        self.assertEqual(status.current_position, "C3")
        self.assertEqual(status.heading, "north")
        self.assertIsNone(status.active_ride_id)
        self.assertEqual(status.last_message, "等待小车上报位置。")

    def test_set_car_position_validates_position_and_heading(self):
        status = self.state.set_car_position(" e5 ", "east")

        self.assertEqual(status.current_position, "E5")
        self.assertEqual(status.heading, "east")
        self.assertEqual(status.last_message, "小车位置已校准为 E5，朝向 east")

        with self.assertRaises(PointValidationError):
            self.state.set_car_position("F1", "north")
        with self.assertRaises(RuntimeStateError) as context:
            self.state.set_car_position("A1", "up")
        self.assertEqual(context.exception.code, "invalid_heading")

    def test_create_ride_sets_active_ride_and_records_passenger_event(self):
        request = RideCreateRequest.from_payload(
            {"start": "A1", "waypoints": ["C2"], "end": "E5"}
        )

        ride = self.state.create_ride(request)
        status = self.state.get_car_status()
        events, next_after = self.state.list_ride_events(ride.id)

        self.assertEqual(ride.status, "dispatching")
        self.assertEqual(ride.current_position, "C3")
        self.assertEqual(ride.progress, ["C3"])
        self.assertEqual(ride.eta_text, "派单中")
        self.assertEqual(ride.mail_status, "pending")
        self.assertEqual(status.mode, "running")
        self.assertEqual(status.active_ride_id, ride.id)
        self.assertEqual(events[0].type, "passenger")
        self.assertEqual(events[0].text, "请求路线 A1 → C2 → E5")
        self.assertEqual(next_after, 1)

    def test_create_ride_rejects_second_active_ride(self):
        request = RideCreateRequest.from_payload(
            {"start": "A1", "waypoints": [], "end": "E5"}
        )
        self.state.create_ride(request)

        with self.assertRaises(RuntimeStateError) as context:
            self.state.create_ride(request)

        self.assertEqual(context.exception.code, "ride_already_running")

    def test_append_and_list_events_after_sequence(self):
        ride = self.state.create_ride(
            RideCreateRequest.from_payload(
                {"start": "A1", "waypoints": [], "end": "E5"}
            )
        )
        self.state.append_ride_event(ride.id, "car", "收到叫车请求，当前上报位置 C3")
        self.state.append_ride_event(ride.id, "car", "已到达起点 A1，请上车")

        events, next_after = self.state.list_ride_events(ride.id, after=1)

        self.assertEqual([event.seq for event in events], [2, 3])
        self.assertEqual(events[0].text, "收到叫车请求，当前上报位置 C3")
        self.assertEqual(next_after, 3)

    def test_update_ride_progress_updates_car_status_and_ride_fields(self):
        ride = self.state.create_ride(
            RideCreateRequest.from_payload(
                {"start": "A1", "waypoints": [], "end": "E5"}
            )
        )

        updated = self.state.update_ride(
            ride.id,
            status="to_pickup",
            current_position="B3",
            heading="east",
            route=["C3", "B3", "A3", "A2", "A1"],
            progress=["C3", "B3"],
            eta_text="来车中",
        )
        car_status = self.state.get_car_status()

        self.assertEqual(updated.status, "to_pickup")
        self.assertEqual(updated.current_position, "B3")
        self.assertEqual(updated.route, ["C3", "B3", "A3", "A2", "A1"])
        self.assertEqual(updated.progress, ["C3", "B3"])
        self.assertEqual(car_status.current_position, "B3")
        self.assertEqual(car_status.heading, "east")
        self.assertEqual(car_status.last_message, "来车中")

    def test_finish_ride_clears_active_ride_for_terminal_status(self):
        ride = self.state.create_ride(
            RideCreateRequest.from_payload(
                {"start": "A1", "waypoints": [], "end": "E5"}
            )
        )

        finished = self.state.finish_ride(
            ride.id,
            status="arrived",
            current_position="E5",
            eta_text="已到达",
        )
        car_status = self.state.get_car_status()

        self.assertEqual(finished.status, "arrived")
        self.assertEqual(finished.current_position, "E5")
        self.assertEqual(car_status.mode, "idle")
        self.assertIsNone(car_status.active_ride_id)

    def test_latest_mail_defaults_and_updates(self):
        latest = self.state.get_latest_mail()

        self.assertEqual(latest.status, "none")
        self.assertEqual(latest.subject, "暂无真实邮件")

        updated = self.state.record_latest_mail(
            status="sent",
            subject="4WD 小车到达通知：E5",
            body="小车已完成路线 A1 → E5，当前位置 E5。",
            error_message=None,
        )

        self.assertEqual(updated.status, "sent")
        self.assertEqual(updated.sent_at, "2026-07-09T15:30:01+08:00")


if __name__ == "__main__":
    unittest.main()
