"""模块之间的契约：工具结果、工具上下文、UI 端口。

这里只有数据结构，没有实现，也不依赖 gi。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ToolResult:
    ok: bool
    text: str
    error_kind: str | None = None       # exception / denied / bad_args / ...
    image: str | None = None            # 截图文件路径
    artifacts: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def ok(text: str, **kw) -> ToolResult:
    return ToolResult(True, str(text), **kw)


def fail(text: str, error_kind: str = "exception", **kw) -> ToolResult:
    return ToolResult(False, str(text), error_kind=error_kind, **kw)


@dataclass
class ToolContext:
    """工具需要的窄接口。UI / agent 不需要把整个 god object 交给工具。"""

    workspace: str
    policy: Any
    confirm: Callable[[str, str], bool]
    panel: Any = None
    memory: Any = None
    before_shot: Callable[[], None] | None = None
    after_shot: Callable[[], None] | None = None
    max_tool_seconds: int = 120
    # agent 的停止信号（threading.Event）；工具靠它打断正在跑的子进程。
    cancel_event: Any = None


class UI(Protocol):
    """agent -> UI 的单向端口。实现方负责把调用切回 GTK 主线程。"""

    def begin_turn(self, text: str, show_user: bool = True) -> None: ...
    def end_turn(self) -> None: ...
    def text_delta(self, text: str) -> None: ...
    def reason_delta(self, text: str) -> None: ...
    def tool_started(self, name: str, args: dict) -> None: ...
    def tool_finished(self, result: ToolResult) -> None: ...
    def queued(self, text: str) -> None: ...
    def notice(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...
    def cancelling(self) -> None: ...
    def effort_changed(self, level: str, reason: str = "") -> None: ...
