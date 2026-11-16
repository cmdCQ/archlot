"""文件与 shell 工具。"""

from __future__ import annotations

import os

from core import system
from core.contracts import ToolResult, fail, ok


def run_shell(tools, a) -> ToolResult:
    cmd = str(a.get("command", "")).strip()
    if not cmd:
        return fail("命令为空", "bad_args")
    try:
        timeout = int(a.get("timeout", 60))
    except (TypeError, ValueError):
        timeout = 60
    timeout = min(max(1, timeout), tools.ctx.max_tool_seconds)
    outside = tools.ctx.policy.outside_write(cmd)
    cancel = getattr(tools.ctx, "cancel_event", None)
    rc, out, err = system.run(["bash", "-lc", cmd],
                              cwd=tools.ctx.workspace, timeout=timeout,
                              cancel=cancel)
    if rc == 130 and cancel is not None and cancel.is_set():
        return fail("已取消。", "cancelled")
    body = out.strip()
    if err.strip():
        body += ("\n[stderr]\n" + err.strip())
    note = f"\n[自动放行] 改动了工作区外：{outside}" if outside else ""
    return ok(
        f"exit={rc}\n{system.clip(body)}{note}",
        meta={"exit": rc, "kind": "act",
              "effect": "confirmed" if rc == 0 else "failed"})


def read_file(tools, a) -> ToolResult:
    path = tools.resolve(a.get("path", ""))
    limit = int(a.get("limit", 20000))
    if not os.path.isfile(path):
        return fail(f"不是文件：{path}", "bad_args")
    with open(path, "r", errors="replace") as f:
        return ok(system.clip(f.read(limit + 1), limit),
                  meta={"kind": "observe"})


def write_file(tools, a) -> ToolResult:
    path = tools.resolve(a.get("path", ""))
    outside = not (path == tools.ctx.workspace or
                   path.startswith(tools.ctx.workspace + os.sep))
    content = str(a.get("content", ""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    note = "（工作区外）" if outside else ""
    return ok(f"已写入 {path}{note}（{len(content)} 字符）",
              artifacts=[path],
              meta={"kind": "act", "effect": "confirmed"})


def list_dir(tools, a) -> ToolResult:
    path = tools.resolve(a.get("path", tools.ctx.workspace))
    try:
        entries = sorted(os.listdir(path))[:200]
    except OSError as exc:
        return fail(f"打不开：{exc}", "bad_args")
    lines = []
    for name in entries:
        full = os.path.join(path, name)
        lines.append(name + ("/" if os.path.isdir(full) else ""))
    return ok("\n".join(lines) or "（空目录）", meta={"kind": "observe"})
