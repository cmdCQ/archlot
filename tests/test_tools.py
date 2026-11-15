import unittest
from types import SimpleNamespace

from tools import HANDLERS, TOOLS, desktop
from ui import appearance


class ToolsRegistryTest(unittest.TestCase):
    def test_schema_and_handlers_match(self):
        names = {t["function"]["name"] for t in TOOLS}
        self.assertEqual(names, set(HANDLERS))
        self.assertEqual(len(names), 16)


class FakePanel:
    """只实现 appearance 工具用到的方法，验证 dispatch 和输出。"""

    def __init__(self):
        self.state = dict(appearance.DEFAULTS)
        self.default = dict(appearance.DEFAULTS)
        self.profiles = {}

    def appearance_info(self):
        info = dict(self.state)
        info["default"] = dict(self.default)
        info["profiles"] = sorted(self.profiles)
        info["presets"] = sorted(appearance.PRESETS)
        return info

    def appearance_set(self, **changes):
        merged = dict(self.state)
        merged.update({k: v for k, v in changes.items()
                       if k in appearance.FIELDS and v is not None})
        self.state = appearance.normalize(merged)
        return self.appearance_info()

    def appearance_preset(self, name):
        preset = appearance.PRESETS.get(name)
        if preset is None:
            return None
        return self.appearance_set(**preset)

    def appearance_reset(self):
        return self.appearance_set(**appearance.DEFAULTS)

    def appearance_save(self, name=None):
        if name in (None, "") or str(name).strip().lower() == "default":
            key = None
        else:
            key = appearance.clean_name(name)
            if key is None:
                return None
        if key is None:
            self.default = dict(self.state)
        else:
            self.profiles[key] = dict(self.state)
        return self.appearance_info()

    def appearance_load(self, name=None):
        is_default = (name in (None, "")
                      or str(name).strip().lower() == "default")
        key = None if is_default else appearance.clean_name(name)
        if is_default:
            state = self.default
        elif key is not None:
            state = self.profiles.get(key)
        else:
            state = None
        if state is None:
            return None
        return self.appearance_set(**state)

    def appearance_delete(self, name):
        key = appearance.clean_name(name)
        if key is None or key not in self.profiles:
            return None
        del self.profiles[key]
        return self.appearance_info()

    def appearance_niri(self):
        return appearance.niri_rule(self.state)


class AppearanceToolTest(unittest.TestCase):
    def setUp(self):
        self.panel = FakePanel()
        self.tools = SimpleNamespace(
            ctx=SimpleNamespace(panel=self.panel))

    def test_info(self):
        result = desktop.appearance(self.tools, {"action": "info"})
        self.assertTrue(result.ok)
        self.assertIn("透明度=0.8", result.text)

    def test_set_single_field(self):
        result = desktop.appearance(
            self.tools, {"action": "set", "accent": "#abc"})
        self.assertTrue(result.ok)
        self.assertEqual(self.panel.state["accent"], "#aabbcc")

    def test_set_requires_a_field(self):
        result = desktop.appearance(self.tools, {"action": "set"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "bad_args")

    def test_preset(self):
        result = desktop.appearance(
            self.tools, {"action": "preset", "preset": "cyan"})
        self.assertTrue(result.ok)
        self.assertEqual(self.panel.state["accent"], "#67e8f9")

    def test_unknown_preset(self):
        result = desktop.appearance(
            self.tools, {"action": "preset", "preset": "nope"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "bad_args")

    def test_niri_action_returns_rule(self):
        result = desktop.appearance(self.tools, {"action": "niri"})
        self.assertTrue(result.ok)
        self.assertIn("window-rule {", result.text)
        self.assertIn("clip-to-geometry true", result.text)

    def test_reset(self):
        self.panel.state["opacity"] = 0.4
        result = desktop.appearance(self.tools, {"action": "reset"})
        self.assertTrue(result.ok)
        self.assertEqual(self.panel.state["opacity"],
                         appearance.DEFAULTS["opacity"])

    def test_save_default_and_restore(self):
        desktop.appearance(self.tools, {"action": "set", "accent": "#112233"})
        result = desktop.appearance(self.tools, {"action": "save"})
        self.assertTrue(result.ok)
        self.assertEqual(self.panel.default["accent"], "#112233")
        self.panel.state["accent"] = "#ffffff"
        result = desktop.appearance(self.tools, {"action": "restore"})
        self.assertTrue(result.ok)
        self.assertEqual(self.panel.state["accent"], "#112233")

    def test_save_load_delete_named_profile(self):
        desktop.appearance(self.tools,
                           {"action": "set", "accent": "#00ff00"})
        result = desktop.appearance(
            self.tools, {"action": "save", "name": "work"})
        self.assertTrue(result.ok)
        self.assertIn("work", result.text)
        desktop.appearance(self.tools,
                           {"action": "set", "accent": "#123456"})
        result = desktop.appearance(
            self.tools, {"action": "load", "name": "work"})
        self.assertTrue(result.ok)
        self.assertEqual(self.panel.state["accent"], "#00ff00")
        result = desktop.appearance(
            self.tools, {"action": "delete", "name": "work"})
        self.assertTrue(result.ok)
        self.assertEqual(self.panel.profiles, {})

    def test_missing_profile(self):
        result = desktop.appearance(
            self.tools, {"action": "load", "name": "nope"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "not_found")

    def test_bad_profile_name(self):
        result = desktop.appearance(
            self.tools, {"action": "save", "name": "x" * 40})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "bad_args")


if __name__ == "__main__":
    unittest.main()
