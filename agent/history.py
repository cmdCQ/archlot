"""消息历史：唯一负责裁剪、配对和截图位置的地方。"""

from __future__ import annotations

import base64
import logging

log = logging.getLogger(__name__)


class MessageHistory:
    """消息历史的唯一所有者，负责裁剪和 provider 需要的不变量。"""

    def __init__(self, max_messages: int = 60):
        self.max_messages = max_messages
        self.items: list[dict] = []

    def add_user(self, text: str) -> None:
        self.items.append({"role": "user", "content": text})

    def add_assistant(self, msg: dict) -> None:
        self.items.append(msg)

    def add_tool(self, call_id: str, text: str) -> None:
        self.items.append({"role": "tool", "tool_call_id": call_id,
                           "content": text})

    def add_image(self, path: str, note: str) -> None:
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except OSError as exc:
            log.warning("读取截图失败：%s", exc)
            return
        self.items.append({"role": "user", "content": [
            {"type": "text", "text": note},
            {"type": "image_url",
             "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]})

    def strip_images(self) -> None:
        for m in self.items:
            content = m.get("content")
            if isinstance(content, list):
                kept = [p for p in content if p.get("type") != "image_url"]
                m["content"] = kept if kept else "（之前的截图已省略）"

    def trim(self) -> None:
        if len(self.items) <= self.max_messages:
            return
        cut = len(self.items) - self.max_messages
        # 优先切在真正的用户消息上；回合内的 agentic 循环里没有这种消息，
        # 退而切在 assistant 边界（tool_calls 组之前），保证不切断配对。
        while cut < len(self.items) and not self._is_turn_start(self.items[cut]):
            cut += 1
        if cut >= len(self.items):
            cut = len(self.items) - self.max_messages
            while cut < len(self.items) and (
                    self.items[cut].get("role") != "assistant"):
                cut += 1
        if cut >= len(self.items):
            return
        head = self.items[:1] if self._is_turn_start(self.items[0]) else []
        marker = [{"role": "user", "content": "（更早的对话已省略）"}]
        self.items = head + marker + self.items[cut:]

    @staticmethod
    def _is_turn_start(m: dict) -> bool:
        # 真正的用户消息是纯字符串；截图消息的 content 是列表
        return m.get("role") == "user" and isinstance(m.get("content"), str)

    def _repair(self) -> None:
        """补全末尾不完整的 tool_calls 组，避免下一次请求 400。

        注意：不能整段丢弃——用户在被中断之后说的那句话往往就排在
        这个残缺组后面，丢掉会让模型完全看不见新指令。
        """
        last = None
        for i, m in enumerate(self.items):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                last = i
        if last is None:
            return
        wanted = [tc.get("id") for tc in self.items[last]["tool_calls"]]
        seen = {m.get("tool_call_id") for m in self.items[last + 1:]
                if m.get("role") == "tool"}
        missing = [cid for cid in wanted if cid not in seen]
        if not missing:
            return
        log.warning("补全被中断的 tool_calls：缺 %s", missing)
        tail = [m for m in self.items[last + 1:] if m.get("role") == "user"]
        fixed = self.items[:last + 1]
        for cid in missing:
            fixed.append({"role": "tool", "tool_call_id": cid,
                          "content": "（该操作被用户中断，未执行）"})
        self.items = fixed + tail

    def payload(self) -> list[dict]:
        self._repair()
        return [dict(m) for m in self.items]

    def last_assistant_text(self) -> str:
        for m in reversed(self.items):
            if m.get("role") == "assistant" and (m.get("content") or "").strip():
                return m["content"]
        return ""

    def snapshot(self) -> list[dict]:
        return [dict(m) for m in self.items]

    def clear(self) -> None:
        self.items = []

    def __len__(self) -> int:
        return len(self.items)
