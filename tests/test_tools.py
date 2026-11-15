import unittest

from tools import HANDLERS, TOOLS


class ToolsRegistryTest(unittest.TestCase):
    def test_schema_and_handlers_match(self):
        names = {t["function"]["name"] for t in TOOLS}
        self.assertEqual(names, set(HANDLERS))
        self.assertEqual(len(names), 14)


if __name__ == "__main__":
    unittest.main()
