import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from agent import Agent
from core.config import Config
from core.contracts import ok
from tools.policy import Policy


class FakeUI:
    def __init__(self):
        self.events = []
        self.done = threading.Event()
        self.errors = []

    def begin_turn(self, text, show_user=True):
        self.events.append(("begin", text, show_user))

    def end_turn(self):
        self.events.append(("end",))
        self.done.set()

    def text_delta(self, text):
        self.events.append(("text", text))

    def reason_delta(self, text):
        pass

    def tool_started(self, name, args):
        self.events.append(("tool", name))

    def tool_finished(self, result):
        self.events.append(("result", result.ok))

    def queued(self, text):
        self.events.append(("queued", text))

    def notice(self, text):
        self.events.append(("notice", text))

    def error(self, text):
        self.errors.append(text)

    def cancelling(self):
        pass


class FakeTools:
    def __init__(self):
        self.calls = []

    def schemas(self):
        return []

    def execute(self, name, args):
        self.calls.append((name, args))
        return ok("done")


class FakeMemory:
    def context_for(self, text):
        return ""

    def consolidate(self):
        return 0


class AgentTurnTest(unittest.TestCase):
    def test_tool_turn_keeps_history_paired(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Config(workspace=tmp.name, max_steps=4, max_turn_seconds=5)
        ui = FakeUI()
        tools = FakeTools()
        responses = [
            ({"role": "assistant", "content": None,
              "reasoning_content": "",
              "tool_calls": [{
                  "id": "c1", "type": "function",
                  "function": {"name": "run_shell",
                               "arguments": "{\"command\": \"true\"}"},
              }]}, "tool_calls"),
            ({"role": "assistant", "content": "ok"}, "stop"),
        ]

        def fake_stream(*args, **kwargs):
            msg, finish = responses.pop(0)
            on_text = kwargs.get("on_text")
            if on_text and msg.get("content"):
                on_text(msg["content"])
            return msg, finish

        with mock.patch("agent.loop.llm.stream_chat", side_effect=fake_stream), \
                mock.patch("agent.loop.HABITS_PATH",
                           os.path.join(tmp.name, "habits.json")):
            agent = Agent(cfg, ui, tools, FakeMemory(),
                          Policy(cfg))
            agent.submit("run")
            self.assertTrue(ui.done.wait(3), "turn did not finish")
            self.assertEqual(tools.calls[0][0], "run_shell")
            self.assertEqual(
                [m["role"] for m in agent.history.items],
                ["user", "assistant", "tool", "assistant"])
            self.assertEqual(ui.errors, [])


if __name__ == "__main__":
    unittest.main()
