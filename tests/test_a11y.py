import tempfile
import unittest
from unittest import mock

from core.contracts import ToolContext
from tools import Tools, a11y


class Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.width, self.height = x, y, w, h


class StateSet:
    def __init__(self, names):
        self.values = {getattr(a11y.Atspi.StateType, n) for n in names}

    def contains(self, state):
        return state in self.values


class Action:
    def __init__(self, *names):
        self.names = list(names)

    def get_n_actions(self):
        return len(self.names)

    def get_action_name(self, index):
        return self.names[index]

    def do_action(self, index):
        return True


class Component:
    def __init__(self, window_rect=None, screen_rect=None):
        self.window_rect = window_rect
        self.screen_rect = screen_rect

    def get_extents(self, coord_type):
        if coord_type == a11y.Atspi.CoordType.WINDOW:
            return self.window_rect
        return self.screen_rect


class Fake:
    def __init__(self, role, name="", children=(), states=("SHOWING", "ENABLED"),
                 actions=(), component=None):
        self.role = role
        self.name = name
        self.children = list(children)
        self.states = StateSet(states)
        self.actions = Action(*actions) if actions else None
        self.component = component

    def get_role_name(self):
        return self.role

    def get_name(self):
        return self.name

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]

    def get_state_set(self):
        return self.states

    def get_action_iface(self):
        return self.actions

    def get_text_iface(self):
        return None

    def get_value_iface(self):
        return None

    def get_editable_text_iface(self):
        return None

    def get_component_iface(self):
        return self.component


@unittest.skipUnless(a11y.AVAILABLE, "AT-SPI 不可用")
class A11yTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tools = Tools(ToolContext(
            workspace=self.tmp.name, policy=None, confirm=lambda *_a: True))
        self.tools._a11y = a11y.A11y()
        self.tools.a11y._inited = True

    def test_begin_turn_clears_snapshots(self):
        snap = a11y.Snap(1, Fake("frame"), {"id": 1})
        self.tools.a11y._snaps[1] = snap
        self.tools.a11y._latest = 1
        self.tools.begin_turn()
        self.assertIsNone(self.tools.a11y._get_snap(None))

    def test_stale_ref_is_rejected(self):
        result = a11y.ui(self.tools, {"action": "read", "ref": "e1"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "stale_ref")

    def test_snapshot_prunes_and_redacts_password(self):
        entry = Fake("entry", "Name")
        password = Fake("password text", "Password")
        button = Fake("button", "Submit", actions=["press"])
        frame = Fake("frame", "Form", children=[entry, password, button])
        window = {"id": 7, "app_id": "app", "title": "Form"}
        with mock.patch.object(a11y, "_match_window", return_value=window), \
                mock.patch.object(a11y, "_frame_for", return_value=frame):
            result = a11y.ui(self.tools, {"action": "snapshot"})
        self.assertTrue(result.ok)
        self.assertIn("snap=1", result.text)
        self.assertIn('e2 entry "Name"', result.text)
        self.assertIn('value="<redacted>"', result.text)
        self.assertIn('e4 button "Submit" [press]', result.text)
        snap = self.tools.a11y._snaps[1]
        self.assertEqual(snap.refs["e2"].path, (0,))

    def test_snapshot_without_tree_points_to_screenshot(self):
        window = {"id": 7, "app_id": "app", "title": "Form"}
        with mock.patch.object(a11y, "_match_window", return_value=window), \
                mock.patch.object(a11y, "_frame_for", return_value=None), \
                mock.patch.object(a11y, "_session_enabled", return_value=False):
            result = a11y.ui(self.tools, {"action": "snapshot"})
        self.assertTrue(result.ok)
        self.assertFalse(result.meta["available"])
        self.assertFalse(result.meta["a11y_session"])
        self.assertIn("AT-SPI", result.text)
        self.assertIn("screenshot", result.text)

    def test_frame_matching_never_borrows_another_window(self):
        frame = Fake("frame", "A11y Form — Mozilla Firefox")
        windows = [
            {"id": 166, "app_id": "firefox", "title": "Mozilla Firefox"},
            {"id": 404, "app_id": "firefox",
             "title": "A11y Form — Mozilla Firefox"},
        ]
        with mock.patch.object(a11y, "_frames",
                               return_value=[("Firefox", frame)]), \
                mock.patch.object(a11y.system, "list_windows",
                                  return_value=windows):
            self.assertIsNone(a11y._frame_for(windows[0]))
            self.assertIs(a11y._frame_for(windows[1]), frame)

    def test_screen_point_uses_window_position(self):
        window = {"id": 7, "layout": {"tile_pos_in_workspace_view": [100, 200]}}
        component = Component(window_rect=Rect(10, 20, 30, 40),
                              screen_rect=Rect(0, 0, 30, 40))
        node = a11y.Node("e1", Fake("button", "Go", component=component),
                         None, window, "button", "Go", 1)
        with mock.patch.object(a11y.system, "screen_size",
                               return_value=(1000, 800)):
            self.assertEqual(a11y._screen_point(node), (125.0, 240.0))

    def test_meaningful_actions_drops_scroll_to_only(self):
        items = [("listitem.scroll-to", 0), ("clickAncestor", 1),
                 ("press", 2)]
        self.assertEqual(a11y._meaningful_actions(items), ["press"])


if __name__ == "__main__":
    unittest.main()
