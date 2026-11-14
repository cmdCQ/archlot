"""DeepSeek（OpenAI 兼容）流式客户端，只用标准库。"""

import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def stream_chat(cfg, messages, tools=None, on_text=None, on_reason=None, cancel=None):
    """发一轮请求，返回 (assistant_message, finish_reason)。

    on_text/on_reason 会在每个增量上被调用（在网络线程里）。
    """
    body = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
        "max_tokens": cfg.get("max_tokens", 4096),
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    req = urllib.request.Request(
        cfg["api_base"].rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "Authorization": "Bearer " + cfg["api_key"],
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise LLMError(f"HTTP {exc.code}：{detail[:400]}") from None
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"连接失败：{exc}") from None

    content, reasoning = [], []
    calls = {}
    finish = None

    with resp:
        for raw in resp:
            if cancel is not None and cancel.is_set():
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}

            if delta.get("reasoning_content"):
                reasoning.append(delta["reasoning_content"])
                if on_reason:
                    on_reason(delta["reasoning_content"])
            if delta.get("content"):
                content.append(delta["content"])
                if on_text:
                    on_text(delta["content"])

            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]

            if choice.get("finish_reason"):
                finish = choice["finish_reason"]

    msg = {"role": "assistant", "content": "".join(content) or None}
    if reasoning:
        msg["reasoning_content"] = "".join(reasoning)
    if calls:
        msg["tool_calls"] = [
            {
                "id": slot["id"] or f"call_{idx}",
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
            }
            for idx, slot in sorted(calls.items())
        ]
    return msg, finish
