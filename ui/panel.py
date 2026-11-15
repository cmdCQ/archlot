"""GTK 面板：窗口、消息渲染、动效、几何、确认框。

这是唯一直接操作 Gtk 控件的地方。agent 通过 UI 端口调用这里的方法，
所有跨线程调用都由本文件自己切回主线程；主线程里不跑 niri 子进程。
提示音在 sound.py，工具卡片文案在 chat.py。
"""

from __future__ import annotations

import json
import logging
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gtk, Pango  # noqa: E402

from core import system  # noqa: E402
from core.config import APP_ID, GEOM_PATH, atomic_write_json  # noqa: E402
from core.contracts import ToolResult  # noqa: E402
from . import markdown  # noqa: E402
from .chat import TOOL_LABELS, tool_preview  # noqa: E402
from .sound import Sound  # noqa: E402

log = logging.getLogger(__name__)

MARGIN = 18
PANEL_W = 380
PANEL_H_MAX = 880


class Panel:
    def __init__(self, app, cfg, css_path=None):
        self.app = app
        self.cfg = cfg
        self.agent = None
        self.win = None
        self.root = None

        self._lock = threading.RLock()
        self._ui_gen = 0
        self._screen = tuple(int(v) for v in system.screen_size())
        self.geom = self._load_geom(self._screen)
        self._min_size = (0, 0)

        self._busy = False
        self._awaiting_confirm = False
        self._confirm_event = None
        self._confirm_ok = False
        self._status_start = 0.0
        self._status_timer = 0

        self._stream_label = None
        self._stream_raw = ""
        self._stream_blink = True
        self._stream_blink_timer = 0
        self._streaming = False
        self._stream_pending = ""
        self._stream_timer = 0
        self._tool_label = None
        self._tool_card = None
        self._reason_buf = ""
        self._reason_timer = 0

        self._has_messages = False
        self._hiding = False
        self._fade_step = 0
        self._shot_focus = None
        self._shot_hid = False
        self._parked = False
        self._park_delta = None

        self._watch_running = False
        self._watch_lock = threading.Lock()

        if css_path:
            self._load_css(css_path)
        self.sound = Sound(cfg)
        self.sound.ensure()
        self._build()
        GLib.timeout_add_seconds(3, self._watch_screen)

    # ------------------------------------------------------------ 线程边界

    @staticmethod
    def _is_main():
        return threading.current_thread() is threading.main_thread()

    def _ui(self, fn, *args):
        """worker -> 主线程，不等待。"""
        if self._is_main():
            fn(*args)
        else:
            GLib.idle_add(self._guarded, fn, args)

    def _main_sync(self, fn, *args, timeout=30):
        """worker -> 主线程并等结果（确认框、截图前隐藏等）。"""
        if self._is_main():
            return fn(*args)
        box = {}
        done = threading.Event()

        def call():
            try:
                box["value"] = fn(*args)
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            finally:
                done.set()
            return False

        GLib.idle_add(call)
        if not done.wait(timeout):
            raise TimeoutError("等待 GTK 主线程超时")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _main_sync_after(self, delay_ms, fn, *args, timeout=30):
        """在主线程延迟执行并等待，用于等合成器处理窗口显隐。"""
        if self._is_main():
            fn(*args)
            return None
        box = {}
        done = threading.Event()

        def call():
            try:
                box["value"] = fn(*args)
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            finally:
                done.set()
            return False

        GLib.timeout_add(delay_ms, call)
        if not done.wait(timeout):
            raise TimeoutError("等待 GTK 主线程超时")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    @staticmethod
    def _guarded(fn, args):
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("UI 回调出错")
        return False

    # ------------------------------------------------------------ 构建界面

    def _load_css(self, path):
        try:
            provider = Gtk.CssProvider()
            provider.load_from_path(path)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception as exc:  # noqa: BLE001
            log.warning("CSS 加载失败：%s", exc)

    def _build(self):
        win = Gtk.ApplicationWindow(application=self.app)
        win.set_title("Archlot")
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_default_size(self.geom["w"], self.geom["h"])
        win.add_css_class("archlot-window")
        self.app.add_window(win)
        self.win = win
        win.connect("close-request", lambda *_: True)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        root.set_size_request(self.geom["w"], self.geom["h"])
        win.set_child(root)
        self.root = root
        self._alpha_provider = Gtk.CssProvider()
        root.get_style_context().add_provider(
            self._alpha_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self._apply_alpha()

        # 顶部状态行
        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.header.add_css_class("header")
        self.header.set_visible(False)
        brand = Gtk.Label(label="ARCHLOT")
        brand.add_css_class("brand")
        brand.set_xalign(0)
        self.thinking_dot = Gtk.Box()
        self.thinking_dot.add_css_class("thinking-dot")
        self.thinking_dot.set_valign(Gtk.Align.CENTER)
        self.thinking_dot.set_visible(False)
        self.status = Gtk.Label(label="")
        self.status.add_css_class("status")
        self.status.set_hexpand(True)
        self.status.set_xalign(1)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        self.header.append(brand)
        self.header.append(self.thinking_dot)
        self.header.append(self.status)
        self.header.append(self.spinner)

        press = Gtk.GestureClick()
        press.set_button(1)
        press.connect("pressed", self._begin_drag)
        self.header.add_controller(press)
        self.header.set_cursor_from_name("grab")
        root.append(self.header)

        # 推理旁白
        self.narration = Gtk.Label(label="")
        self.narration.add_css_class("narration")
        self.narration.set_xalign(0)
        self.narration.set_ellipsize(Pango.EllipsizeMode.END)
        self.narration.set_visible(False)
        root.append(self.narration)

        # 对话区
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.set_visible(False)
        root.append(self.scroll)

        self._stick_bottom = True
        self._scroll_programmatic = False
        adj = self.scroll.get_vadjustment()
        if adj is not None:
            adj.connect("changed", self._on_scroll_changed)
            adj.connect("value-changed", self._on_scroll_value)

        self.msgbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.msgbox.add_css_class("messages")
        self.msgbox.set_valign(Gtk.Align.END)
        self.scroll.set_child(self.msgbox)

        # 空状态
        self.empty_state = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.empty_state.add_css_class("empty-state")
        self.empty_title = Gtk.Label(label="需要我做什么？")
        self.empty_title.add_css_class("empty-title")
        self.empty_title.set_xalign(0)
        empty_hint = Gtk.Label(label="执行命令 · 读写文件 · 看屏幕 · 搜网页")
        empty_hint.add_css_class("empty-hint")
        empty_hint.set_xalign(0)
        empty_hint.set_wrap(True)
        self.empty_state.append(self.empty_title)
        self.empty_state.append(empty_hint)
        self.empty_revealer = Gtk.Revealer()
        self.empty_revealer.set_transition_type(
            Gtk.RevealerTransitionType.CROSSFADE)
        self.empty_revealer.set_transition_duration(240)
        self.empty_revealer.set_child(self.empty_state)
        self.empty_revealer.set_reveal_child(True)
        self.msgbox.append(self.empty_revealer)

        # 确认条
        self.confirm_revealer = Gtk.Revealer()
        self.confirm_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_UP)
        cbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cbox.add_css_class("confirm-bar")
        cbox.set_margin_start(14)
        cbox.set_margin_end(14)
        cbox.set_margin_bottom(6)
        self.confirm_label = Gtk.Label()
        self.confirm_label.set_xalign(0)
        self.confirm_label.set_wrap(True)
        self.confirm_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.confirm_label.set_lines(4)
        self.confirm_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.confirm_label.set_max_width_chars(24)
        self.confirm_label.set_hexpand(True)
        self.confirm_label.add_css_class("confirm-text")
        cbox.append(self.confirm_label)
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_halign(Gtk.Align.END)
        yes = Gtk.Button(label="允许")
        no = Gtk.Button(label="拒绝")
        for b in (yes, no):
            b.add_css_class("small")
            btns.append(b)
        yes.connect("clicked", lambda *_: self._answer_confirm(True))
        no.connect("clicked", lambda *_: self._answer_confirm(False))
        cbox.append(btns)
        self.confirm_revealer.set_child(cbox)
        root.append(self.confirm_revealer)

        # 输入区
        self.divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.divider.add_css_class("divider")
        self.divider.set_visible(False)
        root.append(self.divider)

        self.inputbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.inputbox.add_css_class("input-bar")
        self.inputbox.set_visible(False)
        self.entry = Gtk.Entry()
        self.entry.set_has_frame(False)
        self.entry.set_hexpand(True)
        self.entry.set_width_chars(1)
        self.entry.set_placeholder_text("问点什么，或者让我去做")
        self.entry.connect("activate", self.on_send)
        send = Gtk.Button(label="↑")
        send.add_css_class("send")
        send.set_valign(Gtk.Align.CENTER)
        send.connect("clicked", lambda *_: self.on_send(self.entry))
        self.inputbox.append(self.entry)
        self.inputbox.append(send)
        root.append(self.inputbox)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

    # ------------------------------------------------------------ UI 端口

    def begin_turn(self, text, show_user=True):
        self._ui(self._begin_turn_main, text, show_user)

    def end_turn(self):
        self._ui(self._end_turn_main)

    def text_delta(self, text):
        self._ui(self._append_assistant_main, text)

    def reason_delta(self, text):
        self._ui(self._append_reason_main, text)

    def tool_started(self, name, args):
        self._ui(self._note_tool_main, name, args)

    def tool_finished(self, result):
        self._ui(self._note_result_main, result)

    def queued(self, text):
        self._ui(self._append_queued_main, text)

    def notice(self, text):
        self._ui(self._append_notice_main, text)

    def error(self, text):
        self._ui(self._append_error_main, text)

    def cancelling(self):
        self._ui(self._cancelling_main)

    # ------------------------------------------------------------ 一轮开始/结束

    def _reset_stream_state(self):
        self._stream_label = None
        self._stream_raw = ""
        self._stream_pending = ""
        if self._stream_timer:
            GLib.source_remove(self._stream_timer)
            self._stream_timer = 0
        if self._stream_blink_timer:
            GLib.source_remove(self._stream_blink_timer)
            self._stream_blink_timer = 0

    def _begin_turn_main(self, text, show_user):
        self._end_stream()
        self._reset_stream_state()
        self._busy = True
        self._set_state("busy")
        self.sound.play("send")
        self._reason_buf = ""
        self.narration.set_visible(False)
        self._status_start = time.time()
        if not self._status_timer:
            self._status_timer = GLib.timeout_add(1000, self._tick_status)
        self.status.set_text("思考中 0s")
        self.status.set_visible(True)
        self.thinking_dot.set_visible(True)
        self.spinner.set_visible(True)
        self.spinner.start()
        self._set_empty(False)
        if show_user:
            self._append_user_main(text)
        if self.win is not None and not self.win.get_visible():
            self.show()

    def _end_turn_main(self):
        self._busy = False
        self._streaming = False
        self._set_state("idle")
        self.sound.play("done")
        if self._reason_timer:
            GLib.source_remove(self._reason_timer)
            self._reason_timer = 0
        self.narration.set_visible(False)
        self._flush_pending()
        self._stop_caret()
        self._stick_bottom = True
        GLib.idle_add(self._scroll_bottom)
        GLib.timeout_add(120, self._scroll_bottom)
        GLib.timeout_add(300, self._scroll_bottom)
        if self._status_timer:
            GLib.source_remove(self._status_timer)
            self._status_timer = 0
        self.status.set_visible(False)
        self.thinking_dot.set_visible(False)
        self.spinner.stop()
        self.spinner.set_visible(False)
        if self.win is not None and self.win.get_visible():
            self.win.present()
            self.entry.grab_focus()

    def _cancelling_main(self):
        self.status.set_text("正在停止…")
        self.status.set_visible(True)

    def _tick_status(self):
        if not self._busy:
            self._status_timer = 0
            return False
        if self._awaiting_confirm:
            self.status.set_text("等待确认")
        else:
            elapsed = int(time.time() - self._status_start)
            self.status.set_text(f"思考中 {elapsed}s")
        return True

    # ------------------------------------------------------------ 用户输入

    def on_send(self, entry):
        text = entry.get_text().strip()
        if not text:
            return
        entry.set_text("")
        if self.agent is not None:
            self.agent.submit(text)

    def _append_user_main(self, text):
        self._end_stream()
        self._tool_label = None
        self._has_messages = True
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bubble.add_css_class("user-bubble")
        bubble.set_halign(Gtk.Align.END)
        label = self._wrap_label(text, "user-text")
        label.set_max_width_chars(30)
        bubble.append(label)
        self._append_animated(bubble)
        GLib.idle_add(self._scroll_bottom)

    def _append_queued_main(self, text):
        self._has_messages = True
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bubble.add_css_class("user-bubble")
        bubble.add_css_class("queued")
        bubble.set_halign(Gtk.Align.END)
        label = self._wrap_label(text, "user-text")
        label.set_max_width_chars(30)
        bubble.append(label)
        self._append_animated(bubble)
        self._append_notice_main("收到，等这步做完。")
        GLib.idle_add(self._scroll_bottom)

    def clear(self):
        if self.agent is not None:
            self.agent.reset()
        if self._confirm_event is not None and not self._confirm_event.is_set():
            self._answer_confirm(False)
        self._ui_gen += 1
        self._busy = False
        if self._status_timer:
            GLib.source_remove(self._status_timer)
            self._status_timer = 0
        self.status.set_visible(False)
        self.thinking_dot.set_visible(False)
        self.spinner.stop()
        self.spinner.set_visible(False)
        self._has_messages = False
        self._end_stream()
        self._tool_label = None
        self._tool_card = None
        self._clear_messages()
        adj = self.scroll.get_vadjustment()
        if adj is not None:
            adj.set_value(0)
        if self.win is not None and self.win.get_visible():
            self.entry.grab_focus()

    def on_key(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if (self._confirm_event is not None
                    and not self._confirm_event.is_set()):
                self._answer_confirm(True)
                return True
        if keyval == Gdk.KEY_Escape:
            if (self._confirm_event is not None
                    and not self._confirm_event.is_set()):
                self._answer_confirm(False)
            elif self._busy and self.agent is not None:
                self.agent.cancel()
            else:
                self.hide()
            return True
        if keyval == Gdk.KEY_l and (state & Gdk.ModifierType.CONTROL_MASK):
            self.clear()
            return True
        return False

    # ------------------------------------------------------------ 确认框

    def confirm(self, title, detail):
        if self._is_main():
            log.error("confirm() 不能在主线程等待")
            return False
        event = threading.Event()
        self._confirm_event = event
        self._confirm_ok = False
        self._ui(self._show_confirm_main, title, detail)
        event.wait()
        self._ui(self._hide_confirm_main)
        return self._confirm_ok

    def _show_confirm_main(self, title, detail):
        if self.win is not None and not self.win.get_visible():
            self.show()
        self._awaiting_confirm = True
        self.status.set_text("等待确认")
        self.status.set_visible(True)
        self.confirm_label.set_text(f"{title}\n{detail[:220]}")
        self.confirm_revealer.set_reveal_child(True)

    def _hide_confirm_main(self):
        self._awaiting_confirm = False
        self.confirm_revealer.set_reveal_child(False)
        if self._busy:
            self.status.set_text("思考中")
            self.status.set_visible(True)

    def _answer_confirm(self, allowed):
        self._awaiting_confirm = False
        self.confirm_revealer.set_reveal_child(False)
        self._confirm_ok = allowed
        if self._busy:
            self.status.set_text("思考中")
        if self._confirm_event is not None:
            self._confirm_event.set()

    # ------------------------------------------------------------ 消息渲染

    def _wrap_label(self, text="", css_class=None):
        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_xalign(0)
        label.set_selectable(True)
        if css_class:
            label.add_css_class(css_class)
        return label

    def _reveal(self, child, slide=True, duration=190):
        rv = Gtk.Revealer()
        rv.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_UP if slide
            else Gtk.RevealerTransitionType.CROSSFADE)
        rv.set_transition_duration(duration)
        rv.set_child(child)
        rv.set_reveal_child(False)
        return rv

    def _append_animated(self, child, slide=True, duration=190):
        rv = self._reveal(child, slide, duration)
        self.msgbox.append(rv)
        GLib.timeout_add(16, self._reveal_now, rv)
        return rv

    @staticmethod
    def _reveal_now(rv):
        rv.set_reveal_child(True)
        return False

    def _set_empty(self, visible, animate=True):
        if visible and not self._has_messages:
            if not self.empty_revealer.get_parent():
                self.msgbox.append(self.empty_revealer)
            if animate:
                GLib.timeout_add(16, self._reveal_now, self.empty_revealer)
            else:
                self.empty_revealer.set_reveal_child(True)
        else:
            self.empty_revealer.set_reveal_child(False)

    def _clear_messages(self):
        gen = self._ui_gen
        kids = []
        child = self.msgbox.get_first_child()
        while child is not None:
            if child is not self.empty_revealer:
                kids.append(child)
            child = child.get_next_sibling()
        for kid in kids:
            if isinstance(kid, Gtk.Revealer):
                kid.set_reveal_child(False)
            else:
                kid.set_opacity(0)
        GLib.timeout_add(220, self._drop_children, kids, gen)

    def _drop_children(self, kids, gen):
        if gen != self._ui_gen:
            return False
        for kid in kids:
            if kid.get_parent() is self.msgbox:
                self.msgbox.remove(kid)
        self._set_empty(True)
        return False

    def _new_assistant_block(self):
        block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        block.add_css_class("assistant-block")
        block.set_halign(Gtk.Align.START)
        name = Gtk.Label(label="ARCHLOT")
        name.set_xalign(0)
        name.add_css_class("assistant-name")
        block.append(name)
        label = self._wrap_label("", "assistant-text")
        label.set_max_width_chars(32)
        block.append(label)
        self._stream_raw = ""
        self._stream_blink = True
        self._stream_blink_timer = 0
        self._streaming = False
        self._has_messages = True
        self._append_animated(block)
        return label

    def _append_assistant_main(self, text):
        if not text:
            return
        if self._stream_label is None:
            self._stream_label = self._new_assistant_block()
        self._streaming = True
        self._stream_pending += text
        if not self._stream_timer:
            self._stream_timer = GLib.timeout_add(40, self._flush_stream)

    def _flush_stream(self):
        self._stream_timer = 0
        if self._stream_pending and self._stream_label is not None:
            self._stream_raw += self._stream_pending
            self._stream_pending = ""
            self._render_stream(caret=self._streaming)
            GLib.idle_add(self._scroll_bottom)
            if self._streaming and not self._stream_blink_timer:
                self._stream_blink_timer = GLib.timeout_add(
                    520, self._blink_stream)
        return False

    def _render_stream(self, caret=True):
        if self._stream_label is None:
            return
        body = markdown.to_markup(self._stream_raw)
        if caret:
            alpha = "58982" if self._stream_blink else "0"
            body += (f'<span foreground="#b9a7f5" alpha="{alpha}">▍</span>')
        self._stream_label.set_markup(body)

    def _blink_stream(self):
        if self._stream_label is None or not self._streaming:
            self._stream_blink_timer = 0
            self._render_stream(caret=False)
            return False
        self._stream_blink = not self._stream_blink
        self._render_stream()
        return True

    def _stop_caret(self):
        if self._stream_blink_timer:
            GLib.source_remove(self._stream_blink_timer)
            self._stream_blink_timer = 0
        self._render_stream(caret=False)

    def _flush_pending(self):
        if self._stream_timer:
            GLib.source_remove(self._stream_timer)
            self._stream_timer = 0
        if self._stream_pending and self._stream_label is not None:
            self._stream_raw += self._stream_pending
        self._stream_pending = ""

    def _end_stream(self):
        self._streaming = False
        self._flush_pending()
        self._stop_caret()
        self._stream_label = None
        if getattr(self, "_stick_bottom", True):
            GLib.idle_add(self._scroll_bottom)

    def _append_reason_main(self, text):
        self._reason_buf = (self._reason_buf + text)[-800:]
        if not self._reason_timer:
            self._reason_timer = GLib.timeout_add(260, self._flush_reason)

    def _flush_reason(self):
        self._reason_timer = 0
        if not self._busy:
            return False
        raw = self._reason_buf.replace("\n", " ")
        for sep in "。！？.!?；;":
            raw = raw.replace(sep, sep + "\n")
        lines = [x.strip() for x in raw.split("\n") if x.strip()]
        if lines:
            self.narration.set_text(lines[-1][-64:])
            self.narration.set_visible(True)
        return False

    def _note_tool_main(self, name, args):
        self._end_stream()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.add_css_class("tool-card")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        dot = Gtk.Box()
        dot.add_css_class("tool-dot")
        dot.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label=TOOL_LABELS.get(name, name))
        title.add_css_class("tool-title")
        title.set_xalign(0)
        status = Gtk.Label(label="")
        status.add_css_class("tool-status")
        status.set_hexpand(True)
        status.set_xalign(1)
        top.append(dot)
        top.append(title)
        top.append(status)
        card.append(top)
        base = tool_preview(name, args)
        detail = Gtk.Label(label=base)
        detail.add_css_class("tool-detail")
        detail.set_xalign(0)
        detail.set_ellipsize(Pango.EllipsizeMode.END)
        detail.set_max_width_chars(40)
        card.append(detail)
        bar = Gtk.Box()
        bar.add_css_class("tool-bar")
        card.append(bar)
        self._has_messages = True
        self._append_animated(card, slide=False, duration=150)
        self._tool_card = {"dot": dot, "status": status, "detail": detail,
                           "bar": bar, "card": card, "base": base}
        self._tool_label = detail
        self._scroll_bottom()

    def _note_result_main(self, result: ToolResult):
        card = self._tool_card
        if not card or self._tool_label is None:
            return
        lines = (result.text or "").strip().splitlines()
        line = lines[0] if lines else ""
        # shell 的 exit 非零也算失败显示，但 ToolResult.ok 仍表示“工具执行了”
        failed = (not result.ok
                  or result.meta.get("exit", 0) not in (0, None))
        card["status"].set_text("✗" if failed else "✓")
        card["status"].add_css_class("tool-err" if failed else "tool-ok")
        card["dot"].add_css_class("tool-dot-done")
        card["bar"].set_visible(False)
        card["card"].add_css_class("tool-done")
        if len(line) > 48:
            line = line[:48] + "…"
        if line:
            card["detail"].set_label(f"{card['base']}  ·  {line}")

    def _append_error_main(self, text):
        self._end_stream()
        self._tool_label = None
        self._set_state("error")

        def back_to_idle():
            if not self._busy:
                self._set_state("idle")
            return False

        GLib.timeout_add(1000, back_to_idle)
        self._has_messages = True
        label = self._wrap_label(f"⚠ {text}", "error-text")
        self._append_animated(label, slide=False)
        GLib.idle_add(self._scroll_bottom)

    def _append_notice_main(self, text):
        self._end_stream()
        self._tool_label = None
        self._has_messages = True
        label = self._wrap_label(text, "notice-text")
        self._append_animated(label, slide=False)
        GLib.idle_add(self._scroll_bottom)

    # ------------------------------------------------------------ 滚动

    def _on_scroll_changed(self, adj):
        if getattr(self, "_stick_bottom", True):
            self._scroll_bottom()

    def _on_scroll_value(self, adj):
        if getattr(self, "_scroll_programmatic", False):
            return
        maxv = max(0.0, adj.get_upper() - adj.get_page_size())
        self._stick_bottom = adj.get_value() >= maxv - 6

    def _scroll_bottom(self):
        adj = self.scroll.get_vadjustment()
        if adj is None:
            return False
        self._scroll_target = max(0.0, adj.get_upper() - adj.get_page_size())
        if not getattr(self, "_scroll_anim", False):
            self._scroll_anim = True
            GLib.timeout_add(16, self._scroll_tick)
        return False

    def _scroll_tick(self):
        adj = self.scroll.get_vadjustment()
        if adj is None:
            self._scroll_anim = False
            return False
        target = max(getattr(self, "_scroll_target", 0.0),
                     adj.get_upper() - adj.get_page_size())
        self._scroll_target = target
        cur = adj.get_value()
        delta = target - cur
        if abs(delta) < 0.5:
            self._scroll_programmatic = True
            adj.set_value(target)
            self._scroll_programmatic = False
            self._scroll_anim = False
            return False
        self._scroll_programmatic = True
        adj.set_value(cur + delta * 0.30)
        self._scroll_programmatic = False
        return True

    # ------------------------------------------------------------ 显示/隐藏

    def show(self):
        log.info("show")
        self._hiding = False
        self._fit_to_screen(self._screen)
        self.header.set_visible(True)
        self.scroll.set_visible(True)
        self.divider.set_visible(True)
        self.inputbox.set_visible(True)
        self.confirm_revealer.set_visible(True)
        self._set_empty(not self._has_messages, animate=False)
        self._apply_chrome()
        if not self.win.get_visible():
            self.win.present()
        self.win.set_opacity(1.0)
        self._apply_alpha()
        self._place()
        self._fade_in()
        self.entry.grab_focus()

    def hide(self):
        log.info("hide")
        if self.win is None or not self.win.get_visible():
            return
        me = self._my_window()
        if me:
            threading.Thread(
                target=system.run,
                args=(["niri", "msg", "action", "move-floating-window",
                       "--id", str(me["id"]), "--x=+44"],),
                kwargs={"timeout": 4},
                daemon=True).start()
        self._hiding = True
        self._fade_step = 0
        GLib.timeout_add(16, self._fade_out)

    def _fade_out(self):
        if self.win is None or not self._hiding:
            return False
        self._fade_step += 1
        self.win.set_opacity(max(0.0, 1.0 - self._fade_step / 12.0))
        if self._fade_step >= 12:
            self._unmap()
            return False
        return True

    def _unmap(self):
        self._hiding = False
        if self.win is not None:
            self.win.set_visible(False)
            self.win.set_opacity(1.0)

    def toggle(self):
        log.info("toggle")
        if self.win is not None and self.win.get_visible():
            self.hide()
        else:
            self.show()

    def request_show(self):
        self._ui(self.show)

    def request_hide(self):
        self._ui(self.hide)

    def _fade_in(self):
        order = [self.header, self.scroll, self.inputbox]
        for widget in order:
            widget.set_opacity(0.0)
        steps = 9

        def run_one(widget, delay):
            def start():
                i = [0]

                def tick():
                    i[0] += 1
                    t = min(1.0, i[0] / steps)
                    widget.set_opacity(1 - (1 - t) ** 3)
                    return i[0] < steps

                GLib.timeout_add(16, tick)
                return False

            GLib.timeout_add(delay, start)

        for idx, widget in enumerate(order):
            run_one(widget, idx * 45)

    # ------------------------------------------------------------ 几何

    def _load_geom(self, screen):
        sw, sh = screen
        h = min(PANEL_H_MAX, int(sh) - 2 * MARGIN)
        default = {"x": int(sw) - MARGIN - PANEL_W,
                   "y": (int(sh) - h) // 2,
                   "w": PANEL_W, "h": h,
                   "opacity": 0.8}
        try:
            with open(GEOM_PATH) as f:
                saved = json.load(f)
            for k in ("x", "y", "w", "h", "opacity"):
                if k in saved:
                    default[k] = saved[k]
        except (OSError, json.JSONDecodeError):
            pass
        return self._clamp_geom(default, screen)

    @staticmethod
    def _clamp_geom(geom, screen):
        sw, sh = screen
        w = max(80, min(int(geom.get("w", PANEL_W)), int(sw) - 2 * MARGIN))
        h = max(60, min(int(geom.get("h", PANEL_H_MAX)), int(sh) - 2 * MARGIN))
        x = min(max(int(geom.get("x", 0)), MARGIN),
                max(MARGIN, int(sw) - MARGIN - w))
        y = min(max(int(geom.get("y", 0)), MARGIN),
                max(MARGIN, int(sh) - MARGIN - h))
        out = dict(geom)
        out.update({"x": x, "y": y, "w": w, "h": h})
        return out

    def _geom_snapshot(self):
        with self._lock:
            return dict(self.geom)

    def _save_geom(self):
        try:
            atomic_write_json(GEOM_PATH, self._geom_snapshot())
        except OSError as exc:
            log.warning("窗口几何保存失败：%s", exc)

    def _fit_to_screen(self, screen):
        """屏幕尺寸变了以后，保持贴边/居中关系并把窗口收回可见范围。"""
        sw, sh = int(screen[0]), int(screen[1])
        with self._lock:
            old = self._screen
            if (sw, sh) == tuple(old):
                return
            os_w, os_h = old
            g = dict(self.geom)
            right = abs((g["x"] + g["w"]) - (os_w - MARGIN)) <= 2
            left = abs(g["x"] - MARGIN) <= 2
            center_y = abs(g["y"] - (os_h - g["h"]) / 2) <= 2
            centered_x = abs(g["x"] - (os_w - g["w"]) / 2) <= 2

            self._screen = (sw, sh)
            g = self._clamp_geom(g, self._screen)
            if right:
                g["x"] = sw - MARGIN - g["w"]
            elif left:
                g["x"] = MARGIN
            elif centered_x:
                g["x"] = (sw - g["w"]) // 2
            if center_y:
                g["y"] = (sh - g["h"]) // 2
            self.geom = self._clamp_geom(g, self._screen)
        self._save_geom()
        if self.win is not None:
            self._apply_panel()

    def _my_window(self):
        return next((w for w in system.list_windows()
                     if w.get("app_id") == APP_ID), None)

    def _move_to(self, x, y, wid=None):
        me = self._my_window() if wid is None else {"id": wid}
        if not me:
            return False
        self._save_geom()
        pos = (me.get("layout") or {}).get("tile_pos_in_workspace_view") or [0, 0]
        dx, dy = round(x - pos[0]), round(y - pos[1])
        if abs(dx) >= 1 or abs(dy) >= 1:
            system.run(["niri", "msg", "action", "move-floating-window",
                        "--id", str(me["id"]), f"--x={dx:+d}", f"--y={dy:+d}"],
                       timeout=4)
        return True

    def _place(self):
        if self.win is None or not self.win.get_visible():
            return False
        g = self._geom_snapshot()
        self.root.set_size_request(g["w"], g["h"])
        threading.Thread(target=self._place_worker, daemon=True).start()
        return False

    def _place_worker(self):
        """刚 present 的窗口不一定马上能被 niri 列出，重试几次再定位。"""
        for _ in range(12):
            if self._my_window():
                g = self._geom_snapshot()
                self._move_to(g["x"], g["y"])
                return
            time.sleep(0.03)

    def _watch_screen(self):
        with self._watch_lock:
            if self._watch_running:
                return True
            self._watch_running = True
        threading.Thread(target=self._watch_worker, daemon=True).start()
        return True

    def _watch_worker(self):
        sw, sh = self._screen
        pos = size = None
        try:
            sw, sh = system.screen_size()
            me = self._my_window()
            layout = (me or {}).get("layout") or {}
            pos = layout.get("tile_pos_in_workspace_view")
            size = layout.get("window_size")
        except Exception as exc:  # noqa: BLE001
            log.warning("读取窗口状态失败：%s", exc)
        finally:
            self._ui(self._watch_apply, int(sw), int(sh), pos, size)

    def _watch_apply(self, sw, sh, pos, size):
        self._watch_running = False
        if (sw, sh) != tuple(self._screen):
            self._fit_to_screen((sw, sh))
        if self._hiding or self._parked:
            return
        if (self.win is None or not self.win.get_visible()
                or not pos or not size):
            return
        x, y = int(round(pos[0])), int(round(pos[1]))
        w, h = int(size[0]), int(size[1])
        with self._lock:
            if (x, y, w, h) == (self.geom["x"], self.geom["y"],
                                self.geom["w"], self.geom["h"]):
                return
            self.geom.update({"x": x, "y": y, "w": w, "h": h})
        self._save_geom()

    def _begin_drag(self, gesture, n_press, x, y):
        surface = self.win.get_surface() if self.win else None
        if surface is None:
            return
        try:
            point = Graphene.Point()
            point.init(x, y)
            res = self.header.compute_point(self.win, point)
            pt = res[-1] if isinstance(res, tuple) else res
            device = gesture.get_current_event_device()
            surface.begin_move(device, 1, pt.x, pt.y,
                               gesture.get_current_event_time())
        except Exception as exc:  # noqa: BLE001
            log.warning("begin_move 失败：%s", exc)

    # ------------------------------------------------------------ 面板自控

    def panel_info(self):
        sw, sh = system.screen_size()
        me = self._my_window()
        layout = (me or {}).get("layout") or {}
        g = self._geom_snapshot()
        pos = layout.get("tile_pos_in_workspace_view") or [g["x"], g["y"]]
        size = layout.get("window_size") or [g["w"], g["h"]]
        min_w, min_h = self._min_size
        return {
            "x": int(pos[0]), "y": int(pos[1]),
            "width": int(size[0]), "height": int(size[1]),
            "screen_width": int(sw), "screen_height": int(sh),
            "visible": bool(me),
            "opacity": round(float(g.get("opacity", 1.0)), 2),
            "min_width": min_w,
            "min_height": min_h,
        }

    def _apply_panel(self):
        with self._lock:
            self.geom = self._clamp_geom(self.geom, self._screen)
            g = dict(self.geom)
        if self.win is not None:
            self.win.set_opacity(1.0)
            self._apply_alpha()
            self._apply_chrome()
            w, h = g["w"], g["h"]
            if w < self.root.get_width() or h < self.root.get_height():
                self.root.set_size_request(max(1, w - 1), max(1, h - 1))
                GLib.timeout_add(20, self._apply_panel_size)
            else:
                self._apply_panel_size()
        return False

    def _apply_panel_size(self):
        g = self._geom_snapshot()
        self.root.set_size_request(g["w"], g["h"])
        mn = self.root.get_preferred_size()[0]
        self._min_size = (int(mn.width), int(mn.height))
        if self.win is not None and self.win.get_visible():
            threading.Thread(
                target=self._move_to,
                args=(g["x"], g["y"]),
                daemon=True).start()
        return False

    def _schedule_apply(self):
        self._ui(self._apply_panel)

    def panel_move(self, x, y):
        with self._lock:
            self.geom["x"], self.geom["y"] = int(x), int(y)
        self._save_geom()
        self._schedule_apply()
        return self.panel_info()

    def panel_resize(self, w, h):
        with self._lock:
            self.geom["w"], self.geom["h"] = int(w), int(h)
        self._save_geom()
        self._schedule_apply()
        return self.panel_info()

    def panel_set(self, x, y, w, h):
        with self._lock:
            self.geom.update({"x": int(x), "y": int(y),
                              "w": int(w), "h": int(h)})
        self._save_geom()
        self._schedule_apply()
        return self.panel_info()

    def panel_dock(self, edge, margin=18, size=None):
        sw, sh = system.screen_size()
        m = int(margin)
        g = self._geom_snapshot()
        if edge in ("left", "right"):
            w = int(size) if size else g["w"]
            h = min(g["h"], int(sh) - 2 * m)
            x = m if edge == "left" else int(sw) - m - w
            y = (int(sh) - h) // 2
        else:
            h = int(size) if size else g["h"]
            w = min(g["w"], int(sw) - 2 * m)
            y = m if edge == "top" else int(sh) - m - h
            x = (int(sw) - w) // 2
        return self.panel_set(x, y, w, h)

    def panel_opacity(self, value):
        try:
            v = max(0.2, min(1.0, float(value)))
        except (TypeError, ValueError):
            v = 1.0
        with self._lock:
            self.geom["opacity"] = v
        self._save_geom()
        self._ui(self._apply_alpha, v)
        return self.panel_info()

    def panel_reset(self):
        sw, sh = system.screen_size()
        h = min(PANEL_H_MAX, int(sh) - 2 * MARGIN)
        return self.panel_set(int(sw) - MARGIN - PANEL_W,
                              (int(sh) - h) // 2, PANEL_W, h)

    # ------------------------------------------------------------ 截图钩子

    def hide_for_shot(self):
        """截图前收起自己的窗口，并记住原来聚焦的窗口。"""
        self._shot_focus = None
        try:
            for w in system.list_windows():
                if w.get("is_focused") and w.get("app_id") != APP_ID:
                    self._shot_focus = w["id"]
                    break
        except Exception:  # noqa: BLE001
            pass
        was_visible = self._main_sync(self._hide_window)
        self._shot_hid = bool(was_visible)
        if self._shot_hid:
            self._main_sync_after(80, lambda: None)

    def _hide_window(self):
        if self.win is not None and self.win.get_visible():
            self.win.set_visible(False)
            return True
        return False

    def show_after_shot(self):
        if not self._shot_hid:
            return
        self._shot_hid = False
        self._main_sync(self._show_window)
        self._main_sync_after(100, lambda: None)
        if self._shot_focus:
            system.run(["niri", "msg", "action", "focus-window",
                        "--id", str(self._shot_focus)], timeout=3)

    def _show_window(self):
        if self.win is not None:
            self.win.set_visible(True)
            self.win.present()

    def park_panel(self, x, y):
        """点击点被自己的面板挡住时，把面板临时挪到角落。"""
        if self.win is None:
            return False
        me = self._my_window()
        if not me:
            return False
        layout = me.get("layout") or {}
        pos = layout.get("tile_pos_in_workspace_view") or [0, 0]
        size = layout.get("window_size") or [PANEL_W, PANEL_H_MAX]
        x0, y0 = pos
        w, h = size
        if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h):
            return False
        sw, sh = system.screen_size()
        target_x = (sw - w - 16) if x < sw / 2 else 16
        target_y = 16
        dx = round(target_x - x0)
        dy = round(target_y - y0)
        self._parked = True
        system.run(["niri", "msg", "action", "move-floating-window",
                    "--id", str(me["id"]), f"--x={dx:+d}", f"--y={dy:+d}"],
                   timeout=4)
        self._park_delta = (dx, dy)
        time.sleep(0.06)
        return True

    def unpark_panel(self):
        delta = self._park_delta
        if not delta:
            return
        me = self._my_window()
        if me:
            dx, dy = delta
            system.run(["niri", "msg", "action", "move-floating-window",
                        "--id", str(me["id"]), f"--x={-dx:+d}", f"--y={-dy:+d}"],
                       timeout=4)
        self._park_delta = None
        self._parked = False

    # ------------------------------------------------------------ 视觉

    def _apply_alpha(self, alpha=None):
        with self._lock:
            a = float(self.geom.get("opacity", 0.8) if alpha is None else alpha)
        a = max(0.2, min(1.0, a))
        try:
            self._alpha_provider.load_from_data(
                (".root { background-color: rgba(17, 17, 22, %.3f); }" % a)
                .encode())
        except Exception as exc:  # noqa: BLE001
            log.warning("alpha 设置失败：%s", exc)

    def _set_state(self, state):
        for name in ("state-idle", "state-busy", "state-error"):
            self.root.remove_css_class(name)
        self.root.add_css_class("state-" + state)

    @staticmethod
    def _greeting():
        h = time.localtime().tm_hour
        if 5 <= h < 11:
            return "早上好"
        if 11 <= h < 18:
            return "下午好"
        if 18 <= h < 23:
            return "晚上好"
        return "夜深了"

    def _apply_chrome(self):
        g = self._geom_snapshot()
        w, h = g["w"], g["h"]
        if not self._has_messages:
            self.empty_title.set_text(f"{self._greeting()}，需要我做什么？")
        self.header.set_visible(h >= 160)
        self._set_empty(not self._has_messages and h >= 240, animate=False)
        narrow = w < 200
        for side in ("start", "end"):
            getattr(self.inputbox, f"set_margin_{side}")(6 if narrow else 14)

