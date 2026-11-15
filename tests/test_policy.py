import unittest

from core.config import Config
from tools.policy import Policy


def policy(mode="auto"):
    return Policy(Config(confirm_mode=mode, workspace="/tmp/archlot-test-ws"))


class PolicyTest(unittest.TestCase):
    def test_sudo_always_asks(self):
        for mode in ("auto", "strict"):
            d = policy(mode).review("run_shell", {"command": "sudo pacman -S x"})
            self.assertEqual(d.action, "ask", mode)

    def test_dangerous_rm_root_asks(self):
        d = policy("auto").review("run_shell", {"command": "rm -rf /"})
        self.assertEqual(d.action, "ask")

    def test_normal_command_allowed(self):
        d = policy("auto").review("run_shell", {"command": "ls -la"})
        self.assertEqual(d.action, "allow")

    def test_tmp_delete_allowed(self):
        d = policy("auto").review("run_shell", {"command": "rm -rf /tmp/foo"})
        self.assertEqual(d.action, "allow")

    def test_outside_write_auto_allowed_but_marked(self):
        d = policy("auto").review(
            "run_shell", {"command": "rm -rf ~/projects/foo"})
        self.assertEqual(d.action, "allow")
        self.assertIn("outside_write", d.reason)

    def test_outside_write_strict_asks(self):
        d = policy("strict").review(
            "run_shell", {"command": "rm -rf ~/projects/foo"})
        self.assertEqual(d.action, "ask")

    def test_etc_redirect_asks(self):
        d = policy("auto").review(
            "run_shell", {"command": "echo x > /etc/foo"})
        self.assertEqual(d.action, "ask")

    def test_write_file_inside_allowed(self):
        d = policy("strict").review("write_file", {"path": "a.txt"})
        self.assertEqual(d.action, "allow")

    def test_write_file_outside_mode(self):
        auto = policy("auto").review("write_file", {"path": "/etc/x"})
        strict = policy("strict").review("write_file", {"path": "/etc/x"})
        self.assertEqual(auto.action, "allow")
        self.assertEqual(strict.action, "ask")

    def test_describe_matches_mode(self):
        self.assertIn("auto", policy("auto").describe())
        self.assertIn("严格", policy("strict").describe())


if __name__ == "__main__":
    unittest.main()
