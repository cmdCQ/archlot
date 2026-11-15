import unittest

from ui import appearance


class NormalizeTest(unittest.TestCase):
    def test_defaults_are_stable(self):
        state = appearance.normalize({})
        self.assertEqual(state, appearance.DEFAULTS)

    def test_clamps_and_coerces(self):
        state = appearance.normalize({
            "opacity": "9", "radius": -4, "font_scale": 5,
            "noise": 1, "accent": "ABC", "background": "#112233",
            "blur": "yes", "xray": "off",
        })
        self.assertEqual(state["opacity"], 1.0)
        self.assertEqual(state["radius"], 0)
        self.assertEqual(state["font_scale"], 1.3)
        self.assertEqual(state["noise"], 0.1)
        self.assertEqual(state["accent"], "#aabbcc")
        self.assertEqual(state["background"], "#112233")
        self.assertTrue(state["blur"])
        self.assertFalse(state["xray"])

    def test_bad_values_fall_back(self):
        state = appearance.normalize({
            "opacity": "loud", "radius": None, "font_scale": [],
            "noise": {}, "accent": "not-a-color",
        })
        for key in ("opacity", "radius", "font_scale", "noise"):
            self.assertEqual(state[key], appearance.DEFAULTS[key])
        self.assertEqual(state["accent"], appearance.DEFAULTS["accent"])

    def test_normalize_drops_unknown_fields(self):
        state = appearance.normalize({"x": 1, "opacity": 0.5})
        self.assertNotIn("x", state)


class CssTest(unittest.TestCase):
    def test_css_uses_state(self):
        css = appearance.css({
            "opacity": 0.5, "background": "#000000", "accent": "#ff0000",
            "radius": 20, "font_scale": 1.2,
        })
        self.assertIn("rgba(0, 0, 0, 0.5)", css)
        self.assertIn("border-radius: 20px", css)
        self.assertIn("#ff0000", css)
        self.assertIn("font-size: 12.60pt", css)  # 10.5 * 1.2

    def test_css_is_valid_for_every_preset(self):
        for preset in appearance.PRESETS.values():
            css = appearance.css(preset)
            self.assertIn(".root {", css)
            self.assertTrue(css.strip().endswith("}"))


class NiriRuleTest(unittest.TestCase):
    def test_blur_rule_uses_radius_and_noise(self):
        rule = appearance.niri_rule({
            "radius": 21, "blur": True, "xray": False, "noise": 0.03})
        self.assertIn("geometry-corner-radius 21", rule)
        self.assertIn("clip-to-geometry true", rule)
        self.assertIn("blur true", rule)
        self.assertIn("xray false", rule)
        self.assertIn("noise 0.030", rule)
        self.assertIn('match app-id=r#"^com\\.cqsomt\\.archlot$"#', rule)

    def test_no_blur_rule_omits_background_effect(self):
        rule = appearance.niri_rule({"blur": False})
        self.assertNotIn("background-effect", rule)

    def test_rule_never_sets_opacity(self):
        # niri 的 opacity 会和 CSS alpha 叠乘，必须留空。
        for preset in appearance.PRESETS.values():
            directives = [line.strip() for line in
                          appearance.niri_rule(preset).splitlines()]
            self.assertFalse(any(line.startswith("opacity")
                                 for line in directives))


if __name__ == "__main__":
    unittest.main()
