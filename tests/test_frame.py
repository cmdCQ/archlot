import os
import tempfile
import unittest
from unittest import mock

from core import system
from core.contracts import ToolContext
from tools import Tools, desktop


class FakeMouse:
    def __init__(self):
        self.clicks = []
        self.moves = []

    def click(self, x, y, button="left", double=False):
        self.clicks.append((x, y, button, double))

    def move(self, x, y):
        self.moves.append((x, y))

    def scroll(self, dy, dx):
        pass


class FrameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ctx = ToolContext(
            workspace=self.tmp.name,
            policy=None,
            confirm=lambda *_a: True,
        )
        self.tools = Tools(ctx)
        self.tools._mouse = FakeMouse()

    def test_shot_keeps_its_own_coordinate_space(self):
        shot = self.tools.add_shot("/tmp/a.jpg", (800, 600),
                                   (1600, 1200), 0.8)
        self.assertEqual(self.tools.get_shot(shot.id), shot)
        self.assertEqual(self.tools.get_shot(), shot)

    def test_click_uses_frame_size_not_current_screen(self):
        shot = self.tools.add_shot("/tmp/a.jpg", (800, 600),
                                   (1600, 1200), 0.8)
        result = desktop.click(
            self.tools, {"x": 100, "y": 200, "frame": shot.id})
        self.assertTrue(result.ok)
        self.assertEqual(self.tools._mouse.clicks[0][:2], (200.0, 400.0))
        self.assertEqual(result.meta["frame"], shot.id)
        self.assertEqual(result.meta["effect"], "sent")

    def test_stale_frame_is_rejected(self):
        self.tools.add_shot("/tmp/a.jpg", (800, 600), (1600, 1200), 0.8)
        result = desktop.click(self.tools, {"x": 1, "y": 2, "frame": 999})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "stale_frame")

    def test_click_without_any_screenshot_is_rejected(self):
        result = desktop.click(self.tools, {"x": 1, "y": 2})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "bad_args")

    def test_frames_do_not_survive_new_turn(self):
        shot = self.tools.add_shot("/tmp/a.jpg", (800, 600),
                                   (1600, 1200), 0.8)
        self.tools.begin_turn()
        self.assertIsNone(self.tools.get_shot(shot.id))
        self.assertIsNone(self.tools.last_frame)

    def test_shot_paths_are_unique(self):
        a = system.new_shot_path()
        b = system.new_shot_path()
        self.addCleanup(lambda: [os.unlink(p) for p in (a, b)
                                 if os.path.exists(p)])
        self.assertNotEqual(a, b)

    def test_grid_filter_labels_image_pixels(self):
        with mock.patch.object(desktop, "_grid_font", return_value="/font"):
            filters = desktop._grid_filter(1638, 1024)
        self.assertIn("drawgrid=w=100", filters)
        self.assertIn("text='1000'", filters)
        self.assertIn("text='800'", filters)


if __name__ == "__main__":
    unittest.main()
