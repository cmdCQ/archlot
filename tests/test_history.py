import unittest

from agent.history import MessageHistory


def assistant_call(call_id="c1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": "run_shell", "arguments": "{}"},
        }],
    }


class MessageHistoryTest(unittest.TestCase):
    def test_complete_tool_group_survives_payload(self):
        h = MessageHistory()
        h.add_user("hi")
        h.add_assistant(assistant_call())
        h.add_tool("c1", "done")
        self.assertEqual([m["role"] for m in h.payload()],
                         ["user", "assistant", "tool"])

    def test_incomplete_tool_group_is_dropped(self):
        h = MessageHistory()
        h.add_user("hi")
        h.add_assistant(assistant_call())
        self.assertEqual([m["role"] for m in h.payload()], ["user"])
        self.assertEqual(len(h.items), 1)

    def test_trim_starts_at_user_turn(self):
        h = MessageHistory(max_messages=3)
        h.add_user("first")
        h.add_assistant({"role": "assistant", "content": "a"})
        h.items.append({"role": "user", "content": [
            {"type": "text", "text": "shot"}]})
        h.add_user("second")
        h.trim()
        self.assertEqual(len(h.items), 1)
        self.assertEqual(h.items[0]["content"], "second")

    def test_strip_images(self):
        h = MessageHistory()
        h.add_user("hi")
        h.items.append({"role": "user", "content": [
            {"type": "text", "text": "shot"},
            {"type": "image_url", "image_url": {"url": "data:x"}},
        ]})
        h.strip_images()
        parts = h.items[-1]["content"]
        self.assertFalse(any(p.get("type") == "image_url" for p in parts))

    def test_last_assistant_text(self):
        h = MessageHistory()
        h.add_user("hi")
        h.add_assistant({"role": "assistant", "content": "  "})
        h.add_assistant({"role": "assistant", "content": "answer"})
        self.assertEqual(h.last_assistant_text(), "answer")


if __name__ == "__main__":
    unittest.main()
