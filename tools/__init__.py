"""工具注册与调度。

工具只做具体动作；要不要确认由 policy 决定，UI 通过 ToolContext 的窄接口访问。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from core import system
from core.contracts import ToolContext, ToolResult, fail, ok
from . import a11y as a11y_tool
from . import desktop, files, recall
from .devices import VirtualMouse
from .schema import TOOLS

log = logging.getLogger(__name__)


@dataclass
class Shot:
    """一张截图的身份与坐标空间；click 必须用它换算。"""

    id: int
    path: str
    image_size: tuple[int, int]
    screen_size: tuple[int, int]
    scale: float


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
    "appearance": desktop.appearance,
    "memory": recall.memory,
    "ui": a11y_tool.ui,
}


class Tools:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._mouse = None
        self._a11y = None
        self._shot_seq = 0
        self._shots: dict[int, Shot] = {}
        self.last_frame: int | None = None
        self._lock = threading.Lock()

    @property
    def mouse(self):
        if self._mouse is None:
            self._mouse = VirtualMouse()
        return self._mouse

    @property
    def a11y(self):
        if self._a11y is None:
            self._a11y = a11y_tool.A11y()
        return self._a11y

    def bind_cancel(self, event) -> None:
        """接上 agent 的停止信号；长命令靠它立刻退出，而不是等超时。"""
        self.ctx.cancel_event = event

    def begin_turn(self) -> None:
        """新一轮清空截图/快照缓存；旧 frame 和 ref 不允许跨轮复用。"""
        self._shots.clear()
        self.last_frame = None
        if self._a11y is not None:
            self._a11y.begin_turn()
        system.cleanup_shots()

    def add_shot(self, path: str, image_size, screen_size,
                 scale: float) -> Shot:
        self._shot_seq += 1
        shot = Shot(
            self._shot_seq, path,
            (int(image_size[0]), int(image_size[1])),
            (int(screen_size[0]), int(screen_size[1])),
            float(scale),
        )
        self._shots[shot.id] = shot
        self.last_frame = shot.id
        # 只保留最近若干帧；文件由 begin_turn 统一清理，
        # 避免把本轮还没编码进历史的图片删掉。
        for old in sorted(self._shots)[:-12]:
            del self._shots[old]
        return shot

    def get_shot(self, frame=None) -> Shot | None:
        if frame is None:
            if self.last_frame is None:
                return None
            return self._shots.get(self.last_frame)
        try:
            fid = int(frame)
        except (TypeError, ValueError):
            return None
        return self._shots.get(fid)

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
