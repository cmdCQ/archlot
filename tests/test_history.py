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

    def test_incomplete_tool_group_is_completed(self):
        """被中断的 tool_calls 组要补占位，不能整段丢掉（否则下一句被吞）。"""
        h = MessageHistory()
        h.add_user("hi")
        h.add_assistant(assistant_call())
        self.assertEqual([m["role"] for m in h.payload()],
                         ["user", "assistant", "tool"])

    def test_user_message_after_interrupt_survives(self):
        """取消后用户说的下一句话必须还在 payload 里。"""
        h = MessageHistory()
        h.add_user("帮我把 /tmp/a 改名")
        h.add_assistant({
            "role": "assistant", "content": None,
            "tool_calls": [
                {"id": c, "type": "function",
                 "function": {"name": "run_shell", "arguments": "{}"}}
                for c in ("c1", "c2", "c3")]})
        h.add_tool("c1", "done")          # 用户在第 2 个工具前点了停止
        h.add_user("接着干，顺便看看日志")
        payload = h.payload()
        self.assertEqual(payload[-1]["content"], "接着干，顺便看看日志")

    def test_trim_starts_at_user_turn(self):
        h = MessageHistory(max_messages=3)
        h.add_user("first")
        h.add_assistant({"role": "assistant", "content": "a"})
        h.items.append({"role": "user", "content": [
            {"type": "text", "text": "shot"}]})
        h.add_user("second")
        h.trim()
        self.assertEqual(h.items[0]["content"], "first")
        self.assertEqual(h.items[-1]["content"], "second")
        self.assertTrue(any("省略" in str(m["content"]) for m in h.items))

    def test_trim_works_inside_one_agentic_turn(self):
        """回合内没有纯字符串 user 消息，也要能靠 assistant 边界裁。"""
        h = MessageHistory(max_messages=10)
        h.add_user("跑个长任务")
        for i in range(30):
            h.add_assistant(assistant_call(f"k{i}"))
            h.add_tool(f"k{i}", "x" * 50)
        h.trim()
        self.assertLessEqual(len(h.items), 12)
        roles = [m["role"] for m in h.items]
        self.assertEqual(roles[0], "user")
        # 裁剪后第一组 tool_calls 仍然完整配对
        self.assertNotEqual(roles[1], "tool")

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
