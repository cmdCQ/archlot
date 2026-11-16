"""停止按钮要能立刻打断长命令，而不是等命令或确认超时。"""

import threading
import time
import unittest
from types import SimpleNamespace

from core import system
from core.contracts import ToolContext
from tools import Tools


class AllowPolicy:
    def review(self, name, args):
        return SimpleNamespace(action="allow", reason="",
                               title="", detail="")

    def outside_write(self, cmd):
        return ""


class CancellableRunTest(unittest.TestCase):
    def test_cancel_kills_a_long_command(self):
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        rc, _, err = system.run(["bash", "-c", "sleep 10"], timeout=30,
                                cancel=cancel)
        self.assertEqual(rc, 130)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn("已取消", err)

    def test_timeout_still_returns_124(self):
        started = time.monotonic()
        rc, _, err = system.run(["bash", "-c", "sleep 5"], timeout=0.3)
        self.assertEqual(rc, 124)
        self.assertLess(time.monotonic() - started, 4)
        self.assertIn("超时", err)

    def test_output_is_captured(self):
        rc, out, err = system.run(["bash", "-c", "printf hello"])
        self.assertEqual((rc, out, err), (0, "hello", ""))


class ShellToolCancelTest(unittest.TestCase):
    def test_run_shell_reports_cancelled(self):
        ctx = ToolContext(workspace="/tmp", policy=AllowPolicy(),
                          confirm=lambda *_a: True)
        tools = Tools(ctx)
        cancel = threading.Event()
        tools.bind_cancel(cancel)
        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        result = tools.execute("run_shell",
                               {"command": "sleep 10", "timeout": 30})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "cancelled")
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
