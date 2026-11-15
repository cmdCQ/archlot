import os
import stat
import tempfile
import unittest

from core import setup
from ui import appearance


class ConfigMergeTest(unittest.TestCase):
    def test_update_config_only_overwrites_given_fields(self):
        raw = {"api_base": "https://a", "model": "m", "max_steps": 600}
        out = setup.update_config(raw, {"api_base": "https://b",
                                        "model": None})
        self.assertEqual(out["api_base"], "https://b")
        self.assertEqual(out["model"], "m")
        self.assertEqual(out["max_steps"], 600)
        self.assertIsNot(raw, out)

    def test_mask_key(self):
        self.assertEqual(setup.mask_key(""), "未配置")
        self.assertEqual(setup.mask_key("short"), "*****")
        self.assertEqual(setup.mask_key("sk-1234567890"), "sk-1…7890")


class HotkeyBlockTest(unittest.TestCase):
    def test_block(self):
        block = setup.hotkey_block("Mod+Shift+XF86TouchpadOff",
                                   "/home/u/.local/bin/archlot")
        self.assertIn("Mod+Shift+XF86TouchpadOff", block)
        self.assertIn('spawn "/home/u/.local/bin/archlot";', block)
        self.assertIn("binds {", block)

    def test_rejects_bad_input(self):
        for keys in ("", "Mod + X", "Mod\nX"):
            with self.assertRaises(ValueError):
                setup.hotkey_block(keys, "/bin/archlot")
        with self.assertRaises(ValueError):
            setup.hotkey_block("Mod+X", '/bad"path')

    def test_managed_block_has_markers(self):
        rule = appearance.niri_rule(appearance.PRESETS["default"])
        block = setup.managed_block(
            "com.cqsomt.archlot", rule,
            "Mod+Shift+XF86TouchpadOff", "/bin/archlot")
        self.assertIn(setup.MARK_BEGIN, block)
        self.assertIn(setup.MARK_END, block)
        self.assertIn("window-rule {", block)


class UpsertTest(unittest.TestCase):
    def test_append_to_existing_config(self):
        old = "// my niri config\nbinds {\n    Mod+Q { close-window; }\n}\n"
        block = setup.managed_block(
            "com.cqsomt.archlot",
            appearance.niri_rule(appearance.DEFAULTS),
            "Mod+Shift+XF86TouchpadOff", "/bin/archlot")
        new = setup.upsert_block(old, block)
        self.assertTrue(new.startswith(old.rstrip()))
        self.assertEqual(new.count(setup.MARK_BEGIN), 1)
        self.assertIn("close-window", new)

    def test_replace_existing_block(self):
        block1 = setup.managed_block(
            "com.cqsomt.archlot", "window-rule {\n}", "Mod+A", "/bin/a")
        block2 = setup.managed_block(
            "com.cqsomt.archlot", "window-rule {\n}", "Mod+B", "/bin/b")
        text = setup.upsert_block("head\n", block1)
        text = setup.upsert_block(text, block2)
        self.assertEqual(text.count(setup.MARK_BEGIN), 1)
        self.assertNotIn("Mod+A", text)
        self.assertIn("Mod+B", text)
        self.assertTrue(text.startswith("head\n"))

    def test_empty_config(self):
        block = setup.managed_block(
            "com.cqsomt.archlot", "window-rule {\n}", "Mod+A", "/bin/a")
        self.assertEqual(setup.upsert_block("", block), block)

    def test_mentions_app_id(self):
        self.assertTrue(setup.mentions_app_id(
            ["match app-id=\"com.cqsomt.archlot\""], "com.cqsomt.archlot"))
        self.assertFalse(setup.mentions_app_id([""], "com.cqsomt.archlot"))


class AtomicWriteTest(unittest.TestCase):
    def test_writes_text_with_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.kdl")
            setup.atomic_write_text(path, "hello\n", mode=0o640)
            with open(path) as f:
                self.assertEqual(f.read(), "hello\n")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)


if __name__ == "__main__":
    unittest.main()
