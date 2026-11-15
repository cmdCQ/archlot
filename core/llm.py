"""DeepSeek（OpenAI 兼容）流式客户端，只用标准库。"""

import json
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def _get(cfg, key, default=None):
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def _open(req):
    """429/5xx 短暂重试；其他错误立即转成 LLMError。"""
    for attempt in range(3):
        try:
            return urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise LLMError(f"HTTP {exc.code}：{detail[:400]}") from None
        except Exception as exc:  # noqa: BLE001
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise LLMError(f"连接失败：{exc}") from None


def build_body(cfg, messages, tools=None, effort=None):
    """构造请求体。default 不发 reasoning_effort；只有 low/high 显式覆盖。"""
    body = {
        "model": _get(cfg, "model"),
        "messages": messages,
        "stream": True,
        "max_tokens": _get(cfg, "max_tokens", 4096),
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if effort in ("low", "high"):
        body["reasoning_effort"] = effort
    return body


def stream_chat(cfg, messages, tools=None, on_text=None, on_reason=None,
                cancel=None, effort=None):
    """发一轮请求，返回 (assistant_message, finish_reason)。

    on_text/on_reason 会在每个增量上被调用（在网络线程里）。
    effort 由 agent 的 Effort 状态机给出；default 时省略该参数。
    """
    body = build_body(cfg, messages, tools, effort)

    req = urllib.request.Request(
        _get(cfg, "api_base").rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "Authorization": "Bearer " + _get(cfg, "api_key", ""),
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    resp = _open(req)

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
            if chunk.get("error"):
                err = chunk["error"]
                if isinstance(err, dict):
                    err = err.get("message") or json.dumps(err, ensure_ascii=False)
                raise LLMError(f"接口返回错误：{err}")
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

    tool_calls = [
        {
            "id": slot["id"] or f"call_{idx}",
            "type": "function",
            "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
        }
        for idx, slot in sorted(calls.items())
    ] if calls else None
    msg = {"role": "assistant", "content": "".join(content) or None}
    if reasoning:
        msg["reasoning_content"] = "".join(reasoning)
    elif tool_calls:
        # 思考模式模型带 tool_calls 时必须回传 reasoning_content；空串也接受。
        msg["reasoning_content"] = ""
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg, finish
