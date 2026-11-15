"""Agent：一轮对话的编排、预算、队列与记忆后处理。

这里不 import gi，也不碰控件；需要更新界面时只调用 UI 端口。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

from core import llm
from core.config import HABITS_PATH, atomic_write_json
from core.contracts import UI, fail
from .history import MessageHistory
from .prompts import EXTRACT_PROMPT, SUMMARY_PROMPT, SYSTEM_PROMPT

log = logging.getLogger(__name__)

# 自动抽取的“偏好”必须有用户原话里的长期信号，避免把一次性的
# “你太冷淡了”推断成“用户不喜欢简短回答”。
_PREFERENCE_CUES = (
    "记住", "以后", "下次", "每次", "总是", "始终", "一律", "默认",
    "我偏好", "我习惯", "我讨厌", "我不喜欢", "我希望你", "我要你",
    "别再", "不要再",
)


def _explicit_preference(text):
    # 会话小结传进来的是“用户：…\n助手：…”的完整记录；
    # 只看用户说的话，别被助手的“以后我会注意”带偏。
    if "用户：" in text:
        text = "\n".join(line for line in text.splitlines()
                         if line.startswith("用户："))
    return any(cue in text for cue in _PREFERENCE_CUES)


class Agent:
    def __init__(self, cfg, ui: UI, tools, memory, policy):
        self.cfg = cfg
        self.ui = ui
        self.tools = tools
        self.memory = memory
        self.policy = policy
        self.history = MessageHistory()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._gen = 0
        self._busy = False
        self._queue: list[tuple[int, str]] = []
        self._pending_nudge: str | None = None
        threading.Thread(target=self._consolidate_memory, daemon=True).start()

    # ---------------------------------------------------------------- 对外

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            if self._busy:
                self._queue.append((self._gen, text))
                queued = True
            else:
                self._busy = True
                queued = False
                gen = self._gen
        if queued:
            self.ui.queued(text)
        else:
            self._begin(text, gen, show_user=True)

    def cancel(self) -> None:
        self._cancel.set()
        self.ui.cancelling()

    def reset(self) -> None:
        snapshot = self.history.snapshot()
        if snapshot:
            threading.Thread(target=self._summarize_session,
                             args=(snapshot,), daemon=True).start()
        with self._lock:
            self._gen += 1
            self._queue.clear()
        self._cancel.set()
        self._pending_nudge = None
        self.history.clear()

    # ---------------------------------------------------------------- 一轮

    def _begin(self, text: str, gen: int, show_user: bool) -> None:
        self._cancel.clear()
        self.ui.begin_turn(text, show_user)
        threading.Thread(target=self._run, args=(text, gen), daemon=True).start()

    def _run(self, text: str, gen: int) -> None:
        issues: list[str] = []
        try:
            if gen != self._gen:
                return
            if hasattr(self.tools, "begin_turn"):
                self.tools.begin_turn()
            self._habit_check(text)
            try:
                mem_ctx = self.memory.context_for(text) or "（暂无）"
            except Exception as exc:  # noqa: BLE001
                log.warning("memory 读取失败：%s", exc)
                mem_ctx = "（暂无）"
            self.history.add_user(text)
            started = time.time()
            steps = 0
            while True:
                if self._cancel.is_set() or gen != self._gen:
                    break
                steps += 1
                if steps > self.cfg.max_steps:
                    self.ui.notice(
                        f"这轮已经执行了 {steps - 1} 步，先停在这里。"
                        "可以让我「继续」，或把任务拆小一点。")
                    break
                if time.time() - started > self.cfg.max_turn_seconds:
                    self.ui.notice("这轮用时过长，先停在这里。可以让我继续。")
                    break
                payload = [{"role": "system",
                            "content": self._system_prompt(mem_ctx)}]
                payload += self.history.payload()
                t0 = time.time()
                msg, finish = llm.stream_chat(
                    self.cfg, payload, self.tools.schemas(),
                    on_text=lambda t: self._text_delta(t, gen),
                    on_reason=lambda t: self._reason_delta(t, gen),
                    cancel=self._cancel,
                )
                log.info("turn=%s llm %.2fs finish=%s",
                         gen, time.time() - t0, finish)
                if self._cancel.is_set() or gen != self._gen:
                    break
                calls = msg.get("tool_calls")
                if not calls:
                    content = (msg.get("content") or "").strip()
                    if content:
                        self.history.add_assistant(msg)
                    if finish == "length":
                        self.ui.notice(
                            "这次回答达到输出上限被截断了。可以让我「继续」，"
                            "或把任务拆小一点。")
                    elif not content:
                        self.ui.notice(
                            "模型这次没有返回内容，任务可能没完成。可以再试一次。")
                    break
                self.history.add_assistant(msg)

                pending_images = []
                for tc in calls:
                    if self._cancel.is_set() or gen != self._gen:
                        break
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError as exc:
                        self.ui.tool_started(name, {})
                        result = fail(f"参数不是合法 JSON：{exc}", "bad_args")
                        self.history.add_tool(tc["id"], result.text)
                        self.ui.tool_finished(result)
                        issues.append(f"{name}: {result.text[:200]}")
                        continue
                    if not isinstance(args, dict):
                        args = {}
                    log.info("turn=%s call %s %s", gen, name,
                             json.dumps(args, ensure_ascii=False)[:220])
                    self.ui.tool_started(name, args)
                    result = self.tools.execute(name, args)
                    if gen != self._gen:
                        return
                    self.history.add_tool(tc["id"], result.text)
                    self.ui.tool_finished(result)
                    if (not result.ok and
                            result.error_kind not in ("denied", "cancelled")):
                        issues.append(f"{name}: {result.text[:200]}")
                    elif result.meta.get("effect") == "failed":
                        issues.append(f"{name}: {result.text[:200]}")
                    if result.image:
                        pending_images.append(
                            (result.image, result.meta.get("frame")))

                # 所有 tool 消息必须紧跟上一条 assistant，图片只能之后补
                if pending_images:
                    self.history.strip_images()
                    for image_path, frame in pending_images:
                        note = ("（这是当前的屏幕截图，坐标以这张图的像素为准）"
                                if frame is None else
                                f"（截图 frame={frame}，坐标以这张图的像素为准）")
                        self.history.add_image(image_path, note)

            last_reply = self.history.last_assistant_text()
            if last_reply and gen == self._gen:
                threading.Thread(target=self._auto_remember,
                                 args=(text, last_reply), daemon=True).start()
                if issues:
                    threading.Thread(target=self._reflect_on_issues,
                                     args=(issues, text, last_reply),
                                     daemon=True).start()
            self.history.trim()
        except llm.LLMError as exc:
            self._error(str(exc), gen)
        except Exception as exc:  # noqa: BLE001
            log.exception("agent 轮次出错")
            self._error(f"{type(exc).__name__}：{exc}", gen)
        finally:
            if self._cancel.is_set() and gen == self._gen:
                self.ui.notice("已停止。")
            self._finish(gen)

    def _finish(self, gen: int) -> None:
        with self._lock:
            self._busy = False
            nxt = None
            while self._queue:
                qgen, qtext = self._queue.pop(0)
                if qgen == self._gen:
                    nxt = qtext
                    break
            if nxt is not None:
                self._busy = True
        if gen == self._gen:
            if self._pending_nudge:
                nudge, self._pending_nudge = self._pending_nudge, None
                self.ui.notice(nudge)
            self.ui.end_turn()
        if nxt is not None:
            self._begin(nxt, self._gen, show_user=False)

    def _text_delta(self, text: str, gen: int) -> None:
        if gen == self._gen:
            self.ui.text_delta(text)

    def _reason_delta(self, text: str, gen: int) -> None:
        if gen == self._gen:
            self.ui.reason_delta(text)

    def _error(self, text: str, gen: int) -> None:
        if gen == self._gen:
            self.ui.error(text)

    def _system_prompt(self, mem_ctx: str) -> str:
        return SYSTEM_PROMPT.format(
            workspace=self.cfg.workspace,
            memory=mem_ctx,
            now=time.strftime("%Y-%m-%d %H:%M %A"),
            tone=self._tone_hint(),
            policy=self.policy.describe(),
        )

    def _tone_hint(self) -> str:
        hour = time.localtime().tm_hour
        if hour >= 23 or hour < 6:
            return "现在是深夜，回答尽量短、语气安静。"
        return ""

    # ---------------------------------------------------------------- 习惯

    @staticmethod
    def _habit_key(text: str) -> str:
        return re.sub(r"[\s，。！？、；：,.!?;:]+", "", text.lower())[:24]

    def _habit_check(self, text: str) -> None:
        key = self._habit_key(text)
        if not key:
            return
        data = {}
        try:
            if os.path.exists(HABITS_PATH):
                with open(HABITS_PATH) as f:
                    data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
        entry = data.setdefault(key, {"count": 0, "asked": False, "last_ask": ""})
        entry["count"] = int(entry.get("count", 0)) + 1
        today = time.strftime("%Y-%m-%d")
        if (entry["count"] >= 3 and not entry.get("asked")
                and entry.get("last_ask") != today):
            entry["asked"] = True
            entry["last_ask"] = today
            self._pending_nudge = ("这个流程你做过几次了，要不要我记成固定做法？"
                                   "说「记住这个流程」就行。")
        try:
            if len(data) > 80:
                data = dict(sorted(data.items(),
                                   key=lambda kv: -int(kv[1].get("count", 0)))[:50])
            atomic_write_json(HABITS_PATH, data)
        except OSError as exc:
            log.warning("习惯记录写入失败：%s", exc)

    # ---------------------------------------------------------------- 自动记忆

    def _parse_json_list(self, content: str) -> list:
        text = (content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _consolidate_memory(self) -> None:
        try:
            merged = self.memory.consolidate()
            if merged:
                log.info("memory consolidate: 合并 %s 条", merged)
        except Exception as exc:  # noqa: BLE001
            log.warning("记忆合并失败：%s", exc)

    def _auto_remember(self, user_text: str, assistant_text: str) -> None:
        if len(user_text) + len(assistant_text) < 20:
            return
        try:
            existing = "\n".join(
                f"- {t[:80]}" for _, t, _ in self.memory.recent(20))
            prompt = EXTRACT_PROMPT.format(
                user=user_text[:1500], assistant=assistant_text[:1500],
                existing=existing or "（空）")
            msg, _ = llm.stream_chat(
                self.cfg, [{"role": "user", "content": prompt}])
            kinds = {"preference": "偏好", "environment": "环境",
                     "project": "项目", "lesson": "经验"}
            for item in self._parse_json_list(msg.get("content") or "")[:3]:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    kind = kinds.get(str(item.get("kind", "")), "通用")
                else:
                    text, kind = str(item), "通用"
                text = str(text or "").strip()
                if kind == "经验" and any(w in text for w in (
                        "色情", "内容政策", "违规", "拒绝提供", "不在可协助范围")):
                    continue
                if kind == "偏好" and not _explicit_preference(user_text):
                    log.info("memory skip [偏好]（无明确表述）: %s", text)
                    continue
                if len(text) >= 4:
                    self.memory.add(text, tags=kind, source="auto")
                    log.info("memory add [%s]: %s", kind, text)
        except Exception as exc:  # noqa: BLE001
            log.warning("自动记忆失败：%s", exc)

    def _reflect_on_issues(self, issues: list[str], user_text: str,
                           reply: str) -> None:
        """任务里出现过真正的工具错误，总结一条可复用的经验。"""
        if not issues:
            return
        prompt = (
            "下面是任务中出现的失败或重试，以及最终结果。\n"
            "请总结一条以后能避免同样问题的技术/操作经验，写成一句通用的话，"
            "不要提这次的具体文件或数字；不要记内容政策或拒绝类结论。\n"
            "只输出这一句话；如果失败是偶然的、没有可复用经验，输出“无”。\n\n"
            "失败：\n" + "\n".join(issues[:6]) +
            "\n\n用户要求：" + user_text[:300] +
            "\n最终回答：" + reply[:400])
        try:
            msg, _ = llm.stream_chat(
                self.cfg, [{"role": "user", "content": prompt}])
            lesson = (msg.get("content") or "").strip().strip('"')
            if lesson and lesson != "无" and 4 <= len(lesson) <= 200:
                self.memory.add(lesson, tags="经验", source="reflect")
                log.info("memory add [经验]: %s", lesson)
        except Exception as exc:  # noqa: BLE001
            log.warning("经验反思失败：%s", exc)

    def _summarize_session(self, messages: list[dict]) -> None:
        try:
            lines = []
            for m in messages[-16:]:
                role = "用户" if m.get("role") == "user" else "助手"
                body = m.get("content")
                if not isinstance(body, str) or not body.strip():
                    continue
                lines.append(f"{role}：{body.strip()[:300]}")
            if len(lines) < 2:
                return
            transcript = "\n".join(lines)
            msg, _ = llm.stream_chat(
                self.cfg,
                [{"role": "user",
                  "content": SUMMARY_PROMPT.format(transcript=transcript)}])
            summary = (msg.get("content") or "").strip()
            if summary:
                self.memory.note("会话小结：\n" + summary[:600])
                log.info("memory note: 会话小结已写入")
            self._auto_remember(transcript, "")
            self._consolidate_memory()
        except Exception as exc:  # noqa: BLE001
            log.warning("会话总结失败：%s", exc)
