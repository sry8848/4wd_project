import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks

os.environ.setdefault("CAR_INITIAL_POSITION", "C3")
os.environ.setdefault("CAR_INITIAL_HEADING", "north")

from src.server import app as server_app
from src.server.runtime_state import RuntimeStateError


class ServerAppNavigationModeTest(unittest.TestCase):
    def tearDown(self):
        server_app.app.state.navigation_hardware = None

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
        active_ride = SimpleNamespace(id="ride-1")

        async def run_lifespan():
            with patch.object(
                server_app,
                "create_grid_navigation_hardware",
                return_value=hardware,
            ) as factory, patch.object(
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
                    factory.assert_called_once()
                    grid = factory.call_args.args[0]
                    self.assertEqual((len(grid), len(grid[0])), (5, 5))

                force_cancel_ride.assert_called_once_with(
                    "ride-1", "server_shutdown"
                )

        asyncio.run(run_lifespan())

        hardware.close.assert_called_once_with()
        self.assertIsNone(server_app.app.state.navigation_hardware)

    def test_submit_ride_uses_hardware_navigator(self):
        ride = SimpleNamespace(id="ride-hardware")
        hardware = SimpleNamespace(navigator=object(), motor=Mock())
        server_app.app.state.navigation_hardware = hardware
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
                {"start": "A1", "waypoints": [], "end": "A2"},
                tasks,
            )

        self.assertIs(result, ride)
        self.assertIs(tasks.tasks[0].func, run_hardware)
        self.assertEqual(tasks.tasks[0].args, (ride.id, hardware.navigator))

    def test_hardware_submit_fails_before_creating_ride_when_not_ready(self):
        tasks = BackgroundTasks()
        with patch.object(
            server_app.ride_service,
            "submit_ride",
        ) as submit:
            with self.assertRaises(RuntimeStateError) as context:
                server_app.submit_ride(
                    {"start": "A1", "waypoints": [], "end": "A2"},
                    tasks,
                )

        self.assertEqual(context.exception.code, "hardware_not_ready")
        submit.assert_not_called()

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
