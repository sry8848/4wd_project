import unittest

from src.server.ride_service import RideService
from src.server.runtime_state import RuntimeState
from src.server.schemas import RideCreateRequest
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
    ):
        self.calls.append((start, end, initial_heading))
        nodes = self.segment_nodes.pop(0) if self.segment_nodes else []
        for node, heading in nodes:
            node_reached_fn(node, heading)
            if self.after_node_fn is not None:
                self.after_node_fn()
            if cancel_requested_fn is not None and cancel_requested_fn():
                return NAV_CANCELED
        return self.results.pop(0) if self.results else NAV_ARRIVED


class RideServiceHardwareRideTest(unittest.TestCase):
    def setUp(self):
        self.state = RuntimeState()
        self.service = RideService(self.state)

    def submit(self, start="A1", waypoints=None, end="E5"):
        request = RideCreateRequest.from_payload(
            {
                "start": start,
                "waypoints": waypoints or [],
                "end": end,
            }
        )
        return self.service.submit_ride(request)

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

        finished = self.service.run_hardware_ride(ride.id, navigator)

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
        self.assertEqual(finished.mail_status, "disabled")
        self.assertEqual(self.state.get_car_status().heading, "south")

    def test_hardware_ride_stops_updating_after_cancel(self):
        ride = self.submit()
        canceled = False

        def cancel_once():
            nonlocal canceled
            if not canceled:
                canceled = True
                self.service.cancel_ride(ride.id)

        navigator = FakeNavigator(
            [[((1, 2), "north"), ((0, 2), "north")]],
            after_node_fn=cancel_once,
        )

        finished = self.service.run_hardware_ride(ride.id, navigator)

        self.assertEqual(finished.status, "canceled")
        self.assertEqual(finished.progress, ["C3", "B3"])
        self.assertEqual(len(navigator.calls), 1)
        self.assertEqual(self.state.get_latest_mail().status, "none")

    def test_hardware_ride_marks_no_path_as_failed(self):
        ride = self.submit()
        navigator = FakeNavigator([[]], results=[NAV_NO_PATH])

        finished = self.service.run_hardware_ride(ride.id, navigator)

        self.assertEqual(finished.status, "failed")
        self.assertIn("无法规划到点位 A1", finished.error_message)
        self.assertEqual(finished.current_position, "C3")
        self.assertEqual(self.state.get_latest_mail().status, "none")


if __name__ == "__main__":
    unittest.main()
