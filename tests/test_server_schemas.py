import unittest

from src.server.point_codec import PointValidationError
from src.server.schemas import (
    CarStatusResponse,
    ErrorResponse,
    GridResponse,
    ObstacleRecordResponse,
    RideCreateRequest,
    RideEventResponse,
    RideStatusResponse,
)


class ServerSchemasTest(unittest.TestCase):
    def test_ride_create_request_normalizes_route_points(self):
        request = RideCreateRequest.from_payload(
            {
                "passenger_id": "Alice",
                "start": " a1 ",
                "waypoints": [" c2 "],
                "end": "e5",
            }
        )

        self.assertEqual(request.passenger_id, "Alice")
        self.assertEqual(request.start, "A1")
        self.assertEqual(request.waypoints, ["C2"])
        self.assertEqual(request.end, "E5")

    def test_ride_create_request_rejects_extra_fields(self):
        with self.assertRaises(PointValidationError) as context:
            RideCreateRequest.from_payload(
                {
                    "passenger_id": "Alice",
                    "start": "A1",
                    "waypoints": [],
                    "end": "E5",
                    "current_position": "C3",
                }
            )

        self.assertEqual(context.exception.code, "invalid_request")
        self.assertEqual(context.exception.field, "current_position")

    def test_ride_create_request_requires_valid_passenger_id(self):
        with self.assertRaises(PointValidationError) as missing:
            RideCreateRequest.from_payload(
                {"start": "A1", "waypoints": [], "end": "E5"}
            )
        self.assertEqual(missing.exception.field, "passenger_id")

        with self.assertRaises(PointValidationError) as invalid:
            RideCreateRequest.from_payload(
                {
                    "passenger_id": 1,
                    "start": "A1",
                    "waypoints": [],
                    "end": "E5",
                }
            )
        self.assertEqual(invalid.exception.code, "invalid_passenger")

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
            passenger_id="Alice",
            start="A1",
            waypoints=["C2"],
            end="E5",
            current_position="B3",
            route=["C3", "B3", "A3", "A2", "A1", "B1", "C1", "C2", "C3", "C4", "C5", "D5", "E5"],
            progress=["C3", "B3"],
            eta_text="来车中",
            error_message=None,
            face_verification_id="face_20260714_100000_123456",
            face_verification_image_url="/api/face-verifications/face_20260714_100000_123456/image",
            created_at="2026-07-09T15:30:00+08:00",
            updated_at="2026-07-09T15:30:03+08:00",
        )

        data = response.to_dict()

        self.assertEqual(data["id"], "ride-1")
        self.assertEqual(data["status"], "to_pickup")
        self.assertEqual(data["passenger_id"], "Alice")
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

    def test_obstacle_response_serializes_complete_frontend_contract(self):
        response = ObstacleRecordResponse(
            id="obstacle_20260714_100000_123456_C3_C4",
            ride_id="ride-1",
            created_at="2026-07-14T10:00:00+00:00",
            from_point="C3",
            to_point="C4",
            distance_cm=12.5,
            obstacle_type="toll",
            detected_color="blue",
            classification_status="success",
            station_id="GATE1",
            recognition_error=None,
            handling_result="continued_current_edge",
            recovery_status=None,
            recovered_point=None,
            image_url="/api/obstacles/obstacle_20260714_100000_123456_C3_C4/image",
            capture_error=None,
        )

        self.assertEqual(
            response.to_dict(),
            {
                "id": "obstacle_20260714_100000_123456_C3_C4",
                "ride_id": "ride-1",
                "created_at": "2026-07-14T10:00:00+00:00",
                "from_point": "C3",
                "to_point": "C4",
                "distance_cm": 12.5,
                "obstacle_type": "toll",
                "detected_color": "blue",
                "classification_status": "success",
                "station_id": "GATE1",
                "recognition_error": None,
                "handling_result": "continued_current_edge",
                "recovery_status": None,
                "recovered_point": None,
                "image_url": "/api/obstacles/obstacle_20260714_100000_123456_C3_C4/image",
                "capture_error": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
