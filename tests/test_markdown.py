import unittest

from ui.markdown import to_markup


class MarkdownTest(unittest.TestCase):
    def test_bold_and_code(self):
        out = to_markup("**hi** `x`")
        self.assertIn("<b>hi</b>", out)
        self.assertIn("font_family=\"monospace\"", out)

    def test_html_escaped(self):
        self.assertIn("&lt;script&gt;", to_markup("<script>"))

    def test_list_and_heading(self):
        out = to_markup("# 标题\n- 第一项")
        self.assertIn('weight="bold"', out)
        self.assertIn("•", out)

    def test_code_block(self):
        out = to_markup("```python\nprint(1)\n```")
        self.assertIn("print(1)", out)
        self.assertIn("monospace", out)

    def test_wide_table_becomes_vertical(self):
        out = to_markup("| name | type | note |\n"
                        "| --- | --- | --- |\n"
                        "| idle | fair | low weight |")
        self.assertIn(">idle</span>", out)
        self.assertIn(">type</span>：fair", out)
        self.assertIn(">note</span>：low weight", out)
        self.assertNotIn("│", out)

    def test_two_column_table_keeps_columns(self):
        out = to_markup("| key | value |\n| --- | --- |\n| a | b |")
        self.assertIn("key", out)
        self.assertIn("│", out)
        self.assertIn("a", out)
        self.assertIn("b", out)


if __name__ == "__main__":
    unittest.main()
