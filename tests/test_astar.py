import unittest

from src.algorithms.astar import Node, astar, format_path, grid_to_string, heuristic


class AStarTest(unittest.TestCase):
    def test_node_stores_position_parent_and_costs(self):
        parent = Node((0, 0))
        node = Node((0, 1), parent=parent, g=1, h=3)

        self.assertEqual(node.position, (0, 1))
        self.assertIs(node.parent, parent)
        self.assertEqual(node.g, 1)
        self.assertEqual(node.h, 3)
        self.assertEqual(node.f, 4)

    def test_heuristic_uses_manhattan_distance(self):
        self.assertEqual(heuristic((0, 0), (3, 4)), 7)

    def test_astar_returns_shortest_path_around_obstacles(self):
        grid = [
            ["A", "A", "A"],
            ["X", "X", "A"],
            ["A", "A", "A"],
        ]

        path = astar(grid, (0, 0), (2, 2))

        self.assertEqual(path, [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)])

    def test_astar_returns_start_when_start_is_end(self):
        grid = [["A"]]

        path = astar(grid, (0, 0), (0, 0))

        self.assertEqual(path, [(0, 0)])

    def test_astar_returns_none_when_no_path_exists(self):
        grid = [
            ["A", "X", "A"],
            ["X", "X", "A"],
            ["A", "A", "A"],
        ]

        path = astar(grid, (0, 0), (2, 2))

        self.assertIsNone(path)

    def test_astar_rejects_obstacle_start_or_end(self):
        grid = [
            ["X", "A"],
            ["A", "A"],
        ]

        with self.assertRaises(ValueError):
            astar(grid, (0, 0), (1, 1))

        with self.assertRaises(ValueError):
            astar(grid, (1, 1), (0, 0))

    def test_astar_rejects_non_rectangular_grid(self):
        grid = [
            ["A", "A"],
            ["A"],
        ]

        with self.assertRaises(ValueError):
            astar(grid, (0, 0), (1, 0))


class FormattingTest(unittest.TestCase):
    def test_format_path_converts_zero_based_coordinates_to_grid_names(self):
        self.assertEqual(format_path([(0, 0), (1, 2), (4, 4)]), ["A1", "B3", "E5"])

    def test_grid_to_string_joins_cells_with_spaces(self):
        grid = [
            ["A", "X"],
            ["A", "A"],
        ]

        self.assertEqual(grid_to_string(grid), "A X\nA A\n")


if __name__ == "__main__":
    unittest.main()
