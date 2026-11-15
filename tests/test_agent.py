import tempfile
import threading
import time
import unittest
from unittest import mock

from agent import Agent
from agent.loop import _explicit_preference
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

    def effort_changed(self, level, reason=""):
        self.events.append(("effort", level, reason))


class FakeTools:
    def __init__(self):
        self.calls = []

    def schemas(self):
        return []

    def execute(self, name, args):
        self.calls.append((name, args))
        return ok("done", meta={"kind": "act", "effect": "sent"})


class FakeMemory:
    def context_for(self, text):
        return ""

    def consolidate(self):
        return 0


class AgentTurnTest(unittest.TestCase):
    def test_preference_needs_explicit_long_term_cue(self):
        self.assertFalse(_explicit_preference("你太简短了"))
        self.assertTrue(_explicit_preference("以后回答别太简短"))

    def test_preference_cue_ignores_assistant_lines(self):
        transcript = "用户：你太简短了\n助手：以后我会注意"
        self.assertFalse(_explicit_preference(transcript))

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

        with mock.patch("agent.loop.llm.stream_chat", side_effect=fake_stream):
            agent = Agent(cfg, ui, tools, FakeMemory(),
                          Policy(cfg))
            agent.submit("run")
            self.assertTrue(ui.done.wait(3), "turn did not finish")
            self.assertEqual(tools.calls[0][0], "run_shell")
            self.assertEqual(
                [m["role"] for m in agent.history.items],
                ["user", "assistant", "tool", "assistant"])
            self.assertEqual(ui.errors, [])

    def test_adaptive_effort_reaches_llm_and_ui(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Config(workspace=tmp.name, max_steps=8, max_turn_seconds=5,
                     adaptive_effort=True)
        ui = FakeUI()
        tools = FakeTools()

        def tool_call(index):
            return ({"role": "assistant", "content": None,
                     "reasoning_content": "",
                     "tool_calls": [{
                         "id": f"c{index}", "type": "function",
                         "function": {"name": "run_shell",
                                      "arguments": "{}"},
                     }]}, "tool_calls")

        responses = [tool_call(1), tool_call(2), tool_call(3),
                     ({"role": "assistant", "content": "ok"}, "stop")]
        levels = []

        def fake_stream(*args, **kwargs):
            levels.append(kwargs.get("effort"))
            msg, finish = responses.pop(0)
            return msg, finish

        with mock.patch("agent.loop.llm.stream_chat", side_effect=fake_stream):
            agent = Agent(cfg, ui, tools, FakeMemory(), Policy(cfg))
            agent.submit("run")
            self.assertTrue(ui.done.wait(3), "turn did not finish")

        self.assertEqual(levels, ["default", "default", "default", "low"])
        self.assertIn(("effort", "low", "连续简单动作，降低思考强度"),
                      ui.events)


if __name__ == "__main__":
    unittest.main()
