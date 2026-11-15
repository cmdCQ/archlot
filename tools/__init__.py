"""工具注册与调度。

工具只做具体动作；要不要确认由 policy 决定，UI 通过 ToolContext 的窄接口访问。
"""

from __future__ import annotations

import logging
import threading

from core import system
from core.contracts import ToolContext, ToolResult, fail, ok
from . import desktop, files, recall
from .devices import VirtualMouse
from .schema import TOOLS

log = logging.getLogger(__name__)

HANDLERS = {
    "run_shell": files.run_shell,
    "read_file": files.read_file,
    "write_file": files.write_file,
    "list_dir": files.list_dir,
    "screenshot": desktop.screenshot,
    "click": desktop.click,
    "move_mouse": desktop.move_mouse,
    "scroll": desktop.scroll,
    "type_text": desktop.type_text,
    "press_key": desktop.press_key,
    "list_windows": desktop.list_windows,
    "focus_window": desktop.focus_window,
    "panel": desktop.panel,
    "memory": recall.memory,
}


class Tools:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._mouse = None
        self.last_shot = None   # (width, height) 图片像素
        self._lock = threading.Lock()

    @property
    def mouse(self):
        if self._mouse is None:
            self._mouse = VirtualMouse()
        return self._mouse

    def resolve(self, path):
        return system.resolve_path(self.ctx.workspace, path)

    @staticmethod
    def schemas():
        return TOOLS

    def execute(self, name, args) -> ToolResult:
        fn = HANDLERS.get(name)
        if fn is None:
            return fail(f"未知工具：{name}", "unknown_tool")
        args = args or {}
        try:
            decision = self.ctx.policy.review(name, args)
        except Exception as exc:  # noqa: BLE001
            log.exception("policy failed for %s", name)
            return fail(f"策略检查出错：{exc}", "policy")
        log.info("policy tool=%s action=%s reason=%s",
                 name, decision.action, decision.reason)
        if decision.action == "deny":
            return fail(decision.detail or "策略拒绝执行。", "denied")
        if decision.action == "ask":
            try:
                allowed = self.ctx.confirm(decision.title, decision.detail)
            except Exception as exc:  # noqa: BLE001
                log.exception("confirm failed")
                return fail(f"确认框出错：{exc}", "confirm")
            if not allowed:
                return fail("用户拒绝了这条操作。", "denied")
        try:
            result = fn(self, args)
            return result if isinstance(result, ToolResult) else ok(str(result))
        except Exception as exc:  # noqa: BLE001
            log.exception("tool %s failed", name)
            return fail(f"工具 {name} 出错：{exc}", "exception")
