import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks

os.environ.setdefault("CAR_INITIAL_POSITION", "C3")
os.environ.setdefault("CAR_INITIAL_HEADING", "north")

from src.server import app as server_app
from src.server.point_codec import PointValidationError
from src.server.runtime_state import RuntimeStateError


class ServerAppNavigationModeTest(unittest.TestCase):
    def tearDown(self):
        server_app.app.state.navigation_hardware = None
        server_app.app.state.backend_camera = None
        server_app.app.state.obstacle_recorder = None
        server_app.app.state.face_verifier = None
        server_app.app.state.face_recorder = None
        server_app.app.state.passenger_ids = ()

    def test_configuration_requires_explicit_real_car_pose(self):
        with self.assertRaises(RuntimeError):
            server_app.load_navigation_configuration({})
        with self.assertRaises(RuntimeError):
            server_app.load_navigation_configuration(
                {"CAR_INITIAL_POSITION": "A1"}
            )

        self.assertEqual(
            server_app.load_navigation_configuration(
                {
                    "CAR_INITIAL_POSITION": "A1",
                    "CAR_INITIAL_HEADING": "east",
                }
            ),
            ("A1", "east"),
        )

    def test_hardware_lifespan_creates_once_then_cancels_and_closes(self):
        hardware = Mock()
        hardware.navigator = object()
        camera = Mock()
        camera.available = True
        active_ride = SimpleNamespace(id="ride-1")

        async def run_lifespan():
            with patch.object(
                server_app,
                "create_grid_navigation_hardware",
                return_value=hardware,
            ) as factory, patch.object(
                server_app,
                "BackendCamera",
                return_value=camera,
            ) as camera_class, patch.object(
                server_app.runtime_state,
                "get_active_ride",
                return_value=active_ride,
            ), patch.object(
                server_app.ride_service,
                "force_cancel_ride",
            ) as force_cancel_ride:
                async with server_app.lifespan(server_app.app):
                    self.assertIs(
                        server_app.app.state.navigation_hardware,
                        hardware,
                    )
                    self.assertIs(server_app.app.state.backend_camera, camera)
                    self.assertIsNotNone(
                        server_app.app.state.obstacle_recorder
                    )
                    factory.assert_called_once()
                    grid = factory.call_args.args[0]
                    self.assertEqual((len(grid), len(grid[0])), (5, 5))

                force_cancel_ride.assert_called_once_with(
                    "ride-1", "server_shutdown"
                )
                camera_class.assert_called_once_with(device=0)

        asyncio.run(run_lifespan())

        hardware.close.assert_called_once_with()
        camera.start.assert_called_once_with()
        camera.close.assert_called_once_with()
        self.assertIsNone(server_app.app.state.navigation_hardware)
        self.assertIsNone(server_app.app.state.backend_camera)
        self.assertIsNone(server_app.app.state.obstacle_recorder)

    def test_camera_start_failure_does_not_block_navigation_backend(self):
        hardware = Mock()
        camera = Mock()
        camera.start.return_value = False
        camera.available = False
        camera.error = "cannot open"

        async def run_lifespan():
            with patch.object(
                server_app,
                "create_grid_navigation_hardware",
                return_value=hardware,
            ), patch.object(
                server_app,
                "BackendCamera",
                return_value=camera,
            ), patch.object(
                server_app.runtime_state,
                "get_active_ride",
                return_value=None,
            ):
                async with server_app.lifespan(server_app.app):
                    self.assertIs(
                        server_app.app.state.navigation_hardware,
                        hardware,
                    )
                    self.assertFalse(
                        server_app.app.state.backend_camera.available
                    )

        asyncio.run(run_lifespan())

        hardware.close.assert_called_once_with()
        camera.close.assert_called_once_with()

    def test_submit_ride_uses_hardware_navigator(self):
        ride = SimpleNamespace(id="ride-hardware")
        hardware = SimpleNamespace(navigator=object(), motor=Mock())
        obstacle_recorder = object()
        camera = SimpleNamespace(available=True)
        face_verifier = object()
        face_recorder = object()
        server_app.app.state.navigation_hardware = hardware
        server_app.app.state.backend_camera = camera
        server_app.app.state.obstacle_recorder = obstacle_recorder
        server_app.app.state.face_verifier = face_verifier
        server_app.app.state.face_recorder = face_recorder
        server_app.app.state.passenger_ids = ("Alice",)
        tasks = BackgroundTasks()
        with patch.object(
            server_app.ride_service,
            "submit_ride",
            return_value=ride,
        ), patch.object(
            server_app.ride_service,
            "run_hardware_ride",
        ) as run_hardware:
            result = server_app.submit_ride(
                {
                    "passenger_id": "Alice",
                    "start": "A1",
                    "waypoints": [],
                    "end": "A2",
                },
                tasks,
            )

        self.assertIs(result, ride)
        self.assertIs(tasks.tasks[0].func, run_hardware)
        self.assertEqual(
            tasks.tasks[0].args,
            (
                ride.id,
                hardware.navigator,
                obstacle_recorder,
                face_verifier,
                face_recorder,
            ),
        )

    def test_hardware_submit_fails_before_creating_ride_when_not_ready(self):
        tasks = BackgroundTasks()
        with patch.object(
            server_app.ride_service,
            "submit_ride",
        ) as submit:
            with self.assertRaises(RuntimeStateError) as context:
                server_app.submit_ride(
                    {
                        "passenger_id": "Alice",
                        "start": "A1",
                        "waypoints": [],
                        "end": "A2",
                    },
                    tasks,
                )

        self.assertEqual(context.exception.code, "hardware_not_ready")
        submit.assert_not_called()

    def test_health_reports_camera_state_without_marking_backend_offline(self):
        server_app.app.state.navigation_hardware = object()
        server_app.app.state.backend_camera = SimpleNamespace(
            available=False,
            error="cannot open camera",
        )

        health = server_app.get_health()

        self.assertTrue(health["ok"])
        self.assertTrue(health["hardware_ready"])
        self.assertFalse(health["camera_ready"])
        self.assertEqual(health["camera_error"], "cannot open camera")

    def test_passenger_list_returns_only_loaded_labels(self):
        server_app.app.state.passenger_ids = ("Alice", "张三")

        self.assertEqual(server_app.list_passengers(), ["Alice", "张三"])

    def test_submit_rejects_unknown_passenger_before_creating_ride(self):
        server_app.app.state.navigation_hardware = SimpleNamespace(navigator=object())
        server_app.app.state.obstacle_recorder = object()
        server_app.app.state.backend_camera = SimpleNamespace(available=True)
        server_app.app.state.face_verifier = object()
        server_app.app.state.face_recorder = object()
        server_app.app.state.passenger_ids = ("Alice",)

        with patch.object(server_app.ride_service, "submit_ride") as submit:
            with self.assertRaisesRegex(PointValidationError, "不在当前已加载"):
                server_app.submit_ride(
                    {
                        "passenger_id": "Bob",
                        "start": "A1",
                        "waypoints": [],
                        "end": "A2",
                    },
                    BackgroundTasks(),
                )

        submit.assert_not_called()

    def test_submit_rejects_unavailable_camera_before_creating_ride(self):
        server_app.app.state.navigation_hardware = SimpleNamespace(navigator=object())
        server_app.app.state.obstacle_recorder = object()
        server_app.app.state.backend_camera = SimpleNamespace(available=False)
        server_app.app.state.passenger_ids = ("Alice",)

        with patch.object(server_app.ride_service, "submit_ride") as submit:
            with self.assertRaises(RuntimeStateError) as context:
                server_app.submit_ride(
                    {
                        "passenger_id": "Alice",
                        "start": "A1",
                        "waypoints": [],
                        "end": "A2",
                    },
                    BackgroundTasks(),
                )

        self.assertEqual(context.exception.code, "camera_not_ready")
        submit.assert_not_called()

    def test_retry_and_confirm_endpoints_reject_bodies_and_delegate(self):
        retry_ride = SimpleNamespace(id="ride-1")
        confirm_ride = SimpleNamespace(id="ride-1")
        with patch.object(
            server_app.ride_service,
            "request_face_verification_retry",
            return_value=retry_ride,
        ) as retry, patch.object(
            server_app.ride_service,
            "confirm_boarding",
            return_value=confirm_ride,
        ) as confirm:
            self.assertIs(
                server_app.retry_face_verification("ride-1", payload=None),
                retry_ride,
            )
            self.assertIs(
                server_app.confirm_boarding("ride-1", payload=None),
                confirm_ride,
            )
            with self.assertRaises(PointValidationError):
                server_app.retry_face_verification("ride-1", payload={})
            with self.assertRaises(PointValidationError):
                server_app.confirm_boarding("ride-1", payload={})

        retry.assert_called_once_with("ride-1")
        confirm.assert_called_once_with("ride-1")

    def test_face_image_rejects_invalid_record_id_before_store_access(self):
        with patch.object(
            server_app.face_verification_store,
            "get_image_path",
        ) as get_image_path:
            with self.assertRaises(PointValidationError):
                server_app.get_face_verification_image("../secret")

        get_image_path.assert_not_called()

    def test_obstacle_list_uses_persistent_store(self):
        records = [SimpleNamespace(id="obstacle-1")]
        with patch.object(
            server_app.obstacle_store,
            "list_records",
            return_value=records,
        ):
            response = server_app.list_obstacles()

        self.assertIs(response, records)

    def test_cancel_requests_next_node_stop_without_immediate_brake(self):
        canceling = SimpleNamespace(
            id="ride-1",
            status="canceling",
            current_position="A1",
            eta_text="取消请求已收到，小车将在前方下一个节点停车",
        )
        hardware = SimpleNamespace(navigator=object(), motor=Mock())
        server_app.app.state.navigation_hardware = hardware
        with patch.object(
            server_app.ride_service,
            "request_cancel_ride",
            return_value=canceling,
        ) as request_cancel_ride:
            response = server_app.cancel_ride("ride-1", payload=None)

        request_cancel_ride.assert_called_once_with(
            "ride-1", "passenger_cancel"
        )
        hardware.motor.brake.assert_not_called()
        self.assertEqual(response["status"], "canceling")


if __name__ == "__main__":
    unittest.main()
