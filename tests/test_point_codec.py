import unittest

from src.server.point_codec import (
    MAX_WAYPOINTS,
    PointValidationError,
    all_points,
    coord_to_point,
    normalize_point,
    point_to_coord,
    route_points_to_coords,
    validate_route_stops,
)


class PointCodecTest(unittest.TestCase):
    def test_all_points_returns_5_by_5_grid_order(self):
        points = all_points()

        self.assertEqual(len(points), 25)
        self.assertEqual(points[:5], ["A1", "A2", "A3", "A4", "A5"])
        self.assertEqual(points[-1], "E5")

    def test_normalize_point_accepts_lowercase_and_spaces(self):
        self.assertEqual(normalize_point(" c3 "), "C3")

    def test_point_to_coord_converts_frontend_point_to_zero_based_coord(self):
        self.assertEqual(point_to_coord("A1"), (0, 0))
        self.assertEqual(point_to_coord("E5"), (4, 4))

    def test_coord_to_point_converts_zero_based_coord_to_frontend_point(self):
        self.assertEqual(coord_to_point((0, 0)), "A1")
        self.assertEqual(coord_to_point((4, 4)), "E5")

    def test_invalid_point_raises_structured_error(self):
        with self.assertRaises(PointValidationError) as context:
            point_to_coord("F1", "start")

        self.assertEqual(context.exception.code, "invalid_point")
        self.assertEqual(context.exception.field, "start")

    def test_validate_route_stops_normalizes_valid_route(self):
        start, waypoints, end = validate_route_stops("a1", [" c2 "], "e5")

        self.assertEqual(start, "A1")
        self.assertEqual(waypoints, ["C2"])
        self.assertEqual(end, "E5")

    def test_validate_route_stops_rejects_same_start_end(self):
        with self.assertRaises(PointValidationError) as context:
            validate_route_stops("A1", [], "A1")

        self.assertEqual(context.exception.code, "same_start_end")

    def test_validate_route_stops_rejects_duplicate_stop(self):
        with self.assertRaises(PointValidationError) as context:
            validate_route_stops("A1", ["B2", "A1"], "E5")

        self.assertEqual(context.exception.code, "duplicate_stop")

    def test_validate_route_stops_rejects_too_many_waypoints(self):
        waypoints = ["A2"] * (MAX_WAYPOINTS + 1)

        with self.assertRaises(PointValidationError) as context:
            validate_route_stops("A1", waypoints, "E5")

        self.assertEqual(context.exception.code, "too_many_waypoints")

    def test_route_points_to_coords_converts_whole_route(self):
        coords = route_points_to_coords("A1", ["B1", "B2"], "C2")

        self.assertEqual(coords, [(0, 0), (1, 0), (1, 1), (2, 1)])


if __name__ == "__main__":
    unittest.main()
