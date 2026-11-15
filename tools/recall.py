"""长期记忆工具。"""

from __future__ import annotations

from core.contracts import ToolResult, fail, ok


def memory(tools, a) -> ToolResult:
    mem = tools.ctx.memory
    if mem is None:
        return fail("记忆模块未启用。", "unavailable")
    action = str(a.get("action", "search"))
    if action == "add":
        text = str(a.get("text", "")).strip()
        if not text:
            return fail("要记的内容为空", "bad_args")
        fid = mem.add(text, tags=str(a.get("tags", "")), source="agent")
        return ok(f"已记住（#{fid}）：{text}")
    if action == "search":
        q = str(a.get("query", "")).strip()
        hits = mem.search(q, limit=int(a.get("limit", 8)))
        if not hits:
            return ok("没有相关记忆")
        return ok("\n".join(f"#{i} {t}" for _, i, t, _ in hits))
    if action == "forget":
        ident = str(a.get("id") or a.get("query") or "").strip()
        if not ident:
            return fail("要删哪条？给 id 或关键词", "bad_args")
        n = mem.forget(ident)
        return ok(f"已删除 {n} 条记忆")
    if action == "list":
        rows = mem.recent(limit=int(a.get("limit", 12)))
        stats = mem.stats()
        if not rows:
            return ok(f"还没有记忆（活跃 {stats['active']} 条）")
        body = "\n".join(f"#{i} {t}" for i, t, _ in rows)
        return ok(f"共 {stats['active']} 条活跃记忆：\n{body}")
    return fail(f"不支持的 action：{action}", "bad_args")
