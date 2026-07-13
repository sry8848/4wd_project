import unittest

from src.server.point_codec import PointValidationError
from src.server.schemas import (
    CarStatusResponse,
    ErrorResponse,
    GridResponse,
    RideCreateRequest,
    RideEventResponse,
    RideStatusResponse,
)


class ServerSchemasTest(unittest.TestCase):
    def test_ride_create_request_normalizes_route_points(self):
        request = RideCreateRequest.from_payload(
            {
                "start": " a1 ",
                "waypoints": [" c2 "],
                "end": "e5",
            }
        )

        self.assertEqual(request.start, "A1")
        self.assertEqual(request.waypoints, ["C2"])
        self.assertEqual(request.end, "E5")

    def test_ride_create_request_rejects_extra_fields(self):
        with self.assertRaises(PointValidationError) as context:
            RideCreateRequest.from_payload(
                {
                    "start": "A1",
                    "waypoints": [],
                    "end": "E5",
                    "current_position": "C3",
                }
            )

        self.assertEqual(context.exception.code, "invalid_request")
        self.assertEqual(context.exception.field, "current_position")

    def test_error_response_serializes_validation_error(self):
        error = PointValidationError("invalid_point", "起点无效", "start")

        response = ErrorResponse.from_validation_error(error)

        self.assertEqual(
            response.to_dict(),
            {
                "error": {
                    "code": "invalid_point",
                    "message": "起点无效",
                    "details": {"field": "start"},
                }
            },
        )

    def test_grid_response_uses_frontend_grid_contract(self):
        response = GridResponse.default()
        data = response.to_dict()

        self.assertEqual(data["rows"], ["A", "B", "C", "D", "E"])
        self.assertEqual(data["cols"], ["1", "2", "3", "4", "5"])
        self.assertEqual(len(data["points"]), 25)
        self.assertEqual(data["points"][0], "A1")
        self.assertEqual(data["points"][-1], "E5")
        self.assertEqual(data["blocked_points"], [])
        self.assertEqual(data["blocked_edges"], [])

    def test_car_status_response_serializes_expected_fields(self):
        response = CarStatusResponse(
            online=True,
            mode="idle",
            current_position="C3",
            heading="north",
            active_ride_id=None,
            last_message="等待小车上报位置。",
            updated_at="2026-07-09T15:30:00+08:00",
        )

        self.assertEqual(
            response.to_dict(),
            {
                "online": True,
                "mode": "idle",
                "current_position": "C3",
                "heading": "north",
                "active_ride_id": None,
                "last_message": "等待小车上报位置。",
                "updated_at": "2026-07-09T15:30:00+08:00",
            },
        )

    def test_ride_status_response_serializes_route_and_progress(self):
        response = RideStatusResponse(
            id="ride-1",
            status="to_pickup",
            start="A1",
            waypoints=["C2"],
            end="E5",
            current_position="B3",
            route=["C3", "B3", "A3", "A2", "A1", "B1", "C1", "C2", "C3", "C4", "C5", "D5", "E5"],
            progress=["C3", "B3"],
            eta_text="来车中",
            error_message=None,
            created_at="2026-07-09T15:30:00+08:00",
            updated_at="2026-07-09T15:30:03+08:00",
        )

        data = response.to_dict()

        self.assertEqual(data["id"], "ride-1")
        self.assertEqual(data["status"], "to_pickup")
        self.assertEqual(data["waypoints"], ["C2"])
        self.assertEqual(data["progress"], ["C3", "B3"])
        self.assertIsNone(data["error_message"])

    def test_event_response_serializes_frontend_fields(self):
        event = RideEventResponse(
            seq=1,
            type="car",
            text="已到达起点 A1，请上车",
            created_at="2026-07-09T15:30:06+08:00",
            obstacle_id=None,
        )
        self.assertEqual(event.to_dict()["type"], "car")
        self.assertIsNone(event.to_dict()["obstacle_id"])


if __name__ == "__main__":
    unittest.main()
