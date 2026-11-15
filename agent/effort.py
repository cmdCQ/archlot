"""自适应思考强度：一个纯状态机，不猜任务难度。

只消费工具结果里的结构化信号：
- 连续 3 个纯动作批次 -> low
- 失败 / stale frame / stale ref -> high，保持 2 次请求
- 观察、查询、混合批次不改变当前级别
- 用户拒绝或取消不升级
"""

from __future__ import annotations

DEFAULT = "default"
LOW = "low"
HIGH = "high"

_IGNORED_KINDS = ("denied", "cancelled")


def _meta(result):
    return getattr(result, "meta", None) or {}


def _failed(result) -> bool:
    if not getattr(result, "ok", False):
        if getattr(result, "error_kind", None) not in _IGNORED_KINDS:
            return True
    return _meta(result).get("effect") == "failed"


def _ignored(result) -> bool:
    return getattr(result, "error_kind", None) in _IGNORED_KINDS


class Effort:
    def __init__(self, enabled=False, low_after=3, hold_requests=2):
        self.enabled = bool(enabled)
        self.low_after = max(1, int(low_after))
        self.hold_requests = max(1, int(hold_requests))
        self.begin_turn()

    def begin_turn(self) -> None:
        self.level = DEFAULT
        self._actions = 0
        self._hold = 0
        self._pending_default = False

    def next_level(self):
        """每次发请求前调用；返回 (level, reason)，reason 只在级别变化时非空。"""
        if not self.enabled:
            return DEFAULT, None
        reason = None
        if self._hold > 0:
            self._hold -= 1
            self.level = HIGH
            if self._hold == 0:
                self._pending_default = True
            return HIGH, None
        if self._pending_default:
            self._pending_default = False
            self.level = DEFAULT
            reason = "高强度执行完，恢复默认"
        if self._actions >= self.low_after and self.level != HIGH:
            if self.level != LOW:
                self.level = LOW
                reason = "连续简单动作，降低思考强度"
        return self.level, reason

    def note_batch(self, results):
        """一批工具执行完后调用；返回 (level, reason)。"""
        results = [r for r in (results or []) if r is not None]
        if not self.enabled or not results:
            return self.level, None

        if any(_failed(r) for r in results):
            self.level = HIGH
            self._hold = self.hold_requests
            self._pending_default = False
            self._actions = 0
            return HIGH, "工具失败，暂时提高思考强度"

        if all(_ignored(r) for r in results):
            return self.level, None

        pure_action = all(_meta(r).get("kind") == "act" for r in results)
        if pure_action:
            self._actions += 1
            if (self._actions >= self.low_after and self._hold == 0
                    and self.level != HIGH):
                if self.level != LOW:
                    self.level = LOW
                    return LOW, "连续简单动作，降低思考强度"
            return self.level, None

        # 观察、查询或混合批次：不切换级别，只打断“连续动作”计数。
        self._actions = 0
        return self.level, None
