import unittest

from tools.desktop import to_screen


class CoordsTest(unittest.TestCase):
    def test_scales_exactly(self):
        self.assertEqual(to_screen(100, 200, (800, 600), (1600, 1200)),
                         (200.0, 400.0))

    def test_no_screenshot_keeps_coords(self):
        self.assertEqual(to_screen(10, 20, None, (1600, 1200)), (10.0, 20.0))

    def test_no_truncation(self):
        x, y = to_screen(1, 1, (999, 999), (1000, 1000))
        self.assertAlmostEqual(x, 1000 / 999)
        self.assertAlmostEqual(y, 1000 / 999)


if __name__ == "__main__":
    unittest.main()
