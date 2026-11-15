#!/usr/bin/env python3
"""Archlot —— 住在 niri 底部的本地 AI 助手。"""

import base64
import json
import os
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import llm  # noqa: E402
from tools import TOOLS, Tools, list_windows, niri_json, run, screen_size  # noqa: E402

APP_ID = "com.cqsomt.archlot"


def _log(msg):
    try:
        with open("/tmp/archlot-app.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass
BASE = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.path.expanduser("~/.config/archlot/config.json")
CSS_PATH = os.path.join(BASE, "style.css")

MARGIN = 18
TAB = 56            # 收起态小方块
PANEL_W = 380       # 展开态侧栏宽度
PANEL_H_MAX = 880

SYSTEM_PROMPT = """你是 Archlot，跑在用户 cqsomt 的 Arch Linux + niri 桌面上的私人 AI 助手。

身份：你就是 Archlot。底层模型是 DeepSeek（deepseek-flash，由深度求索提供）。
被问到模型身份时，只回答：我是 Archlot，底层是 DeepSeek 的 deepseek-flash 模型。不要展开猜测。

回答用中文，直接、简短，不要客套话和废话。
输出纯文本：不要用 Markdown 标记（**、#、```、表格竖线），需要强调就用普通句子。

你有真正能干活的工具：执行 shell、读写文件、看屏幕、动鼠标、敲键盘、切窗口。

工作区：{workspace}
- 所有新建文件、脚本、下载和临时产物都放进工作区，不要写到家目录根下或别处。
- 工作区外默认只读；确需改动工作区外的文件时先说明原因，程序会弹确认。
- 只在真的需要看屏幕或找不着目标位置时才 screenshot；单纯打字、按键后不必截图。
- 坐标用最近一张截图的像素坐标。点按钮、输入框这类目标时，点它的中心，不要点边框或边缘（差几像素就会点空）。
- 填表单时先把所有字段填完，最后截一张图确认内容对不对；发现点空了就重新点输入框中心再输入。
- 能安全合并的连续动作放在同一轮里一次做完（例如 focus_window + press_key + type_text 一起调用），减少来回；只有结果不确定时才停下来看。
- type_text / press_key 默认 auto 就够用；但如果目标是不认键盘协议的界面（网页版远程控制台 noVNC / KVM / IPMI、部分游戏），输入会丢字或变成数字，按键也没反应，这时改用 method="keys" 走真实键码重做。
- 判断依据：输入后截图发现字符缺失、变成数字或根本没出现，就是键盘协议不兼容，别反复重试 auto。
- 你可以用 panel 工具调整自己的窗口：位置、尺寸、贴边停靠、透明度、收起或唤出。用户让你改自己的样子或位置时直接调，不用问。
- 危险命令（删除、sudo、关机等）会由程序弹窗让用户确认，你不用反复口头询问。
- 绝不编造工具结果。做不到就直说做不到。
"""


def load_config():
    cfg = {
        "api_base": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "max_tokens": 4096,
        "workspace": os.path.expanduser("~/archlot-workspace"),
    }
    try:
        with open(CONF_PATH) as f:
            cfg.update(json.load(f))
    except (OSError, json.JSONDecodeError):
        pass
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")
    return cfg


class Archlot(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.cfg = load_config()
        self.win = None
        self.messages = []
        self.busy = False
        workspace = self.cfg.get("workspace") or os.path.expanduser("~/archlot-workspace")
        os.makedirs(workspace, exist_ok=True)
        self.workspace = os.path.abspath(os.path.expanduser(workspace))
        self.tools = Tools(self, self.workspace)
        self._confirm_event = None
        self._confirm_ok = False

    # ------------------------------------------------------------ 生命周期

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        self.ensure_ui()
        if "--toggle" in args:
            self.toggle()
        elif "--daemon" in args:
            pass
        else:
            self.show()
        return 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        try:
            provider = Gtk.CssProvider()
            provider.load_from_path(CSS_PATH)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"CSS 加载失败：{exc}", file=sys.stderr)

    def ensure_ui(self):
        if self.win is not None:
            return
        if not getattr(self, "geom", None):
            self.geom = self._load_geom()
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("Archlot")
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_default_size(self.geom["w"], self.geom["h"])
        win.add_css_class("archlot-window")
        self.add_window(win)
        self.win = win
        win.connect("close-request", lambda *_: (_log("close-request"), True)[1])

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        root.set_size_request(self.geom["w"], self.geom["h"])
        win.set_child(root)
        self.root = root
        self._last_external = None

        # 顶部状态行
        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.header.add_css_class("header")
        self.header.set_visible(False)
        brand = Gtk.Label(label="ARCHLOT")
        brand.add_css_class("brand")
        brand.set_xalign(0)
        self.status = Gtk.Label(label="")
        self.status.add_css_class("status")
        self.status.set_hexpand(True)
        self.status.set_xalign(1)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        self.header.append(brand)
        self.header.append(self.status)
        self.header.append(self.spinner)
        root.append(self.header)

        # 对话区
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.set_visible(False)
        root.append(self.scroll)

        self.msgbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.msgbox.add_css_class("messages")
        self.msgbox.set_valign(Gtk.Align.START)
        self.scroll.set_child(self.msgbox)

        self._cancel = threading.Event()
        self._gen = 0
        self._stream_label = None
        self._stream_pending = ""
        self._stream_timer = 0
        self._tool_label = None

        # 空状态
        self.empty_state = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.empty_state.add_css_class("empty-state")
        empty_title = Gtk.Label(label="需要我做什么？")
        empty_title.add_css_class("empty-title")
        empty_title.set_xalign(0)
        empty_hint = Gtk.Label(label="执行命令 · 读写文件 · 看屏幕 · 搜网页")
        empty_hint.add_css_class("empty-hint")
        empty_hint.set_xalign(0)
        empty_hint.set_wrap(True)
        self.empty_state.append(empty_title)
        self.empty_state.append(empty_hint)
        self.msgbox.append(self.empty_state)

        # 确认条
        self.confirm_revealer = Gtk.Revealer()
        self.confirm_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        cbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cbox.add_css_class("confirm-bar")
        cbox.set_margin_start(14)
        cbox.set_margin_end(14)
        cbox.set_margin_bottom(6)
        self.confirm_label = Gtk.Label()
        self.confirm_label.set_xalign(0)
        self.confirm_label.set_wrap(True)
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
        self.entry.set_placeholder_text("问点什么，或者让我去做")
        self.entry.connect("activate", self.on_send)
        send = Gtk.Button(label="\u2191")
        send.add_css_class("send")
        send.set_valign(Gtk.Align.CENTER)
        send.connect("clicked", lambda *_: self.on_send(self.entry))
        self.inputbox.append(self.entry)
        self.inputbox.append(send)
        root.append(self.inputbox)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

    # ------------------------------------------------------------ 文本渲染

    def _tick_status(self):
        if not self.busy:
            return False
        if getattr(self, "_awaiting_confirm", False):
            self.status.set_text("等待确认")
        else:
            elapsed = int(time.time() - getattr(self, "_status_start", time.time()))
            self.status.set_text(f"思考中 {elapsed}s")
        return True

    def cancel_agent(self):
        self._cancel.set()
        self.status.set_text("正在停止…")
        self.status.set_visible(True)

    def _scroll_bottom(self):
        adj = self.scroll.get_vadjustment()
        if adj is not None:
            adj.set_value(adj.get_upper())
        return False

    def _clear_messages(self):
        child = self.msgbox.get_first_child()
        while child is not None:
            self.msgbox.remove(child)
            child = self.msgbox.get_first_child()

    def _wrap_label(self, text="", css_class=None):
        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_xalign(0)
        label.set_selectable(True)
        if css_class:
            label.add_css_class(css_class)
        return label

    def append_user(self, text):
        self._end_stream()
        self._tool_label = None
        self.msgbox.set_valign(Gtk.Align.START)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bubble.add_css_class("user-bubble")
        bubble.set_halign(Gtk.Align.END)
        label = self._wrap_label(text, "user-text")
        label.set_max_width_chars(30)
        bubble.append(label)
        self.msgbox.append(bubble)
        GLib.idle_add(self._scroll_bottom)

    def append_assistant(self, text, gen=None):
        if gen is not None and gen != self._gen:
            return False
        text = text.replace("`", "").replace("**", "")
        if not text:
            return False
        if self._stream_label is None:
            self._stream_label = self._new_assistant_block()
        self._stream_pending += text
        if not self._stream_timer:
            self._stream_timer = GLib.timeout_add(40, self._flush_stream)
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
        self.msgbox.append(block)
        return label

    def _flush_stream(self):
        self._stream_timer = 0
        if self._stream_label is not None and self._stream_pending:
            self._stream_label.set_label(
                self._stream_label.get_label() + self._stream_pending)
            self._stream_pending = ""
            GLib.idle_add(self._scroll_bottom)
        return False

    def _end_stream(self):
        if self._stream_timer:
            GLib.source_remove(self._stream_timer)
            self._stream_timer = 0
        if self._stream_pending and self._stream_label is not None:
            self._stream_label.set_label(
                self._stream_label.get_label() + self._stream_pending)
            self._stream_pending = ""
        self._stream_label = None

    def note_tool(self, name, args, gen=None):
        if gen is not None and gen != self._gen:
            return False
        self._end_stream()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.add_css_class("tool-row")
        icon = Gtk.Label(label="⚙")
        icon.add_css_class("tool-icon")
        text = Gtk.Label(label=name)
        text.add_css_class("tool-text")
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.set_hexpand(True)
        text.set_xalign(0)
        row.append(icon)
        row.append(text)
        self.msgbox.append(row)
        self._tool_label = text
        self._scroll_bottom()
        return False

    def note_result(self, text, gen=None):
        if gen is not None and gen != self._gen:
            return False
        if self._tool_label is None:
            return False
        first = (text or "").strip().splitlines()
        line = first[0] if first else ""
        if len(line) > 60:
            line = line[:60] + "…"
        if line:
            self._tool_label.set_label(self._tool_label.get_label() + "  ·  " + line)
        return False

    def append_error(self, text, gen=None):
        if gen is not None and gen != self._gen:
            return False
        self._end_stream()
        self._tool_label = None
        label = self._wrap_label(f"⚠ {text}", "error-text")
        self.msgbox.append(label)
        GLib.idle_add(self._scroll_bottom)
        return False

    def append_notice(self, text, gen=None):
        if gen is not None and gen != self._gen:
            return False
        self._end_stream()
        self._tool_label = None
        label = self._wrap_label(text, "notice-text")
        self.msgbox.append(label)
        GLib.idle_add(self._scroll_bottom)
        return False

    # ------------------------------------------------------------ 显示/隐藏

    # ------------------------------------------------------------ 窗口几何

    GEOM_PATH = os.path.expanduser("~/.config/archlot/window.json")

    def _load_geom(self):
        sw, sh = screen_size()
        h = min(PANEL_H_MAX, int(sh) - 2 * MARGIN)
        default = {"x": int(sw) - MARGIN - PANEL_W,
                   "y": (int(sh) - h) // 2,
                   "w": PANEL_W, "h": h,
                   "opacity": 1.0}
        try:
            with open(self.GEOM_PATH) as f:
                saved = json.load(f)
            for k in ("x", "y", "w", "h", "opacity"):
                if k in saved:
                    default[k] = saved[k]
        except (OSError, json.JSONDecodeError):
            pass
        return default

    def _save_geom(self):
        try:
            os.makedirs(os.path.dirname(self.GEOM_PATH), exist_ok=True)
            with open(self.GEOM_PATH, "w") as f:
                json.dump(self.geom, f)
        except OSError:
            pass

    def _my_window(self):
        return next((w for w in list_windows()
                     if w.get("app_id") == APP_ID), None)

    def _move_to(self, x, y, wid=None):
        me = self._my_window() if wid is None else {"id": wid}
        if not me:
            return False
        self._save_geom()
        pos = (me.get("layout") or {}).get("tile_pos_in_workspace_view") or [0, 0]
        dx, dy = round(x - pos[0]), round(y - pos[1])
        if abs(dx) >= 1 or abs(dy) >= 1:
            run(["niri", "msg", "action", "move-floating-window",
                 "--id", str(me["id"]), f"--x={dx:+d}", f"--y={dy:+d}"],
                timeout=4)
        return True

    def _place(self):
        if self.win is None or not self.win.get_visible():
            return False
        self.root.set_size_request(self.geom["w"], self.geom["h"])
        GLib.timeout_add(20, lambda: self._move_to(self.geom["x"], self.geom["y"]))
        return False

    # ------------------------------------------------------------ 显示/隐藏

    def show(self):
        _log("show")
        self.ensure_ui()
        self._remember_external_focus()
        self.header.set_visible(True)
        self.scroll.set_visible(True)
        self.divider.set_visible(True)
        self.inputbox.set_visible(True)
        self.confirm_revealer.set_visible(True)
        self.empty_state.set_visible(not self.messages)
        if not self.win.get_visible():
            self.win.present()
        self.win.set_opacity(self.geom.get("opacity", 1.0))
        self._place()
        self.entry.grab_focus()

    def _remember_external_focus(self):
        try:
            for w in list_windows():
                if w.get("is_focused") and w.get("app_id") != APP_ID:
                    self._last_external = w["id"]
                    return
        except Exception:  # noqa: BLE001
            pass

    def hide(self):
        """先向右滑出屏幕，再 unmap，避免在桌面上留一个小方块。"""
        _log("hide")
        if self.win is None or not self.win.get_visible():
            return
        me = self._my_window()
        if me:
            pos = (me.get("layout") or {}).get("tile_pos_in_workspace_view") or [0, 0]
            sw, _ = screen_size()
            dx = round(sw - pos[0] + 40)
            run(["niri", "msg", "action", "move-floating-window",
                 "--id", str(me["id"]), f"--x={dx:+d}"], timeout=4)
        GLib.timeout_add(150, self._unmap)

    def _unmap(self):
        if self.win is not None:
            self.win.set_visible(False)
        if self._last_external:
            GLib.timeout_add(60, self._refocus_external)
        return False

    def _refocus_external(self):
        run(["niri", "msg", "action", "focus-window",
             "--id", str(self._last_external)], timeout=3)
        return False

    def toggle(self):
        _log("toggle")
        if self.win is not None and self.win.get_visible():
            self.hide()
        else:
            self.show()

    def on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if self._confirm_event is not None and not self._confirm_event.is_set():
                self._answer_confirm(False)
            elif self.busy:
                self.cancel_agent()
            else:
                self.hide()
            return True
        if keyval == Gdk.KEY_l and (state & Gdk.ModifierType.CONTROL_MASK):
            self.clear()
            return True
        return False

    def clear(self):
        self._gen += 1
        if self.busy:
            self._cancel.set()
        self.busy = False
        if getattr(self, "_status_timer", None):
            GLib.source_remove(self._status_timer)
            self._status_timer = None
        self.status.set_visible(False)
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.messages = []
        self._end_stream()
        self._clear_messages()
        self._tool_label = None
        self.collapse()

    def collapse(self):
        self.hide()

    # ------------------------------------------------------------ 对话

    def on_send(self, entry):
        if self.busy:
            return
        text = entry.get_text().strip()
        if not text:
            return
        entry.set_text("")
        self.busy = True
        self._cancel.clear()
        self._status_start = time.time()
        self._status_timer = GLib.timeout_add(1000, self._tick_status)
        self.status.set_text("思考中 0s")
        self.status.set_visible(True)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.empty_state.set_visible(False)
        self.append_user(text)
        if self.win is not None and not self.win.get_visible():
            self.show()
        threading.Thread(target=self.run_agent, args=(text,), daemon=True).start()

    def run_agent(self, text):
        gen = self._gen
        self.messages.append({"role": "user", "content": text})
        try:
            while True:
                if self._cancel.is_set() or gen != self._gen:
                    break
                payload = [{"role": "system",
                            "content": SYSTEM_PROMPT.format(workspace=self.workspace)}] + self.messages
                _t0 = time.time()
                msg, _finish = llm.stream_chat(
                    self.cfg, payload, TOOLS,
                    on_text=lambda t: GLib.idle_add(self.append_assistant, t, gen),
                    cancel=self._cancel,
                )
                _log(f"llm {time.time() - _t0:.2f}s finish={_finish}")
                if self._cancel.is_set():
                    break
                if gen != self._gen:
                    return
                self.messages.append(msg)
                calls = msg.get("tool_calls")
                if not calls:
                    if not (msg.get("content") or "").strip():
                        GLib.idle_add(
                            self.append_notice,
                            "模型这次没有返回内容，任务可能没完成。可以再试一次。", gen)
                    break
                pending_images = []
                for tc in calls:
                    if self._cancel.is_set() or gen != self._gen:
                        break
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    _log(f"call {name} {json.dumps(args, ensure_ascii=False)[:220]}")
                    GLib.idle_add(self.note_tool, name, args, gen)
                    _t1 = time.time()
                    result = self.tools.execute(name, args)
                    _log(f"tool {name} {time.time() - _t1:.2f}s")
                    if gen != self._gen:
                        return
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result["text"],
                    })
                    GLib.idle_add(self.note_result, result["text"], gen)
                    if result.get("image"):
                        pending_images.append(result["image"])
                # 所有 tool 消息必须紧跟上一条 assistant，图片只能之后补
                if pending_images:
                    self.strip_old_images()
                for image_path in pending_images:
                    with open(image_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    self.messages.append({"role": "user", "content": [
                        {"type": "text",
                         "text": "（这是当前的屏幕截图，坐标以这张图的像素为准）"},
                        {"type": "image_url",
                         "image_url": {"url": "data:image/jpeg;base64," + b64}},
                    ]})
            self.trim_history()
        except llm.LLMError as exc:
            GLib.idle_add(self.append_error, str(exc), gen)
        except Exception as exc:  # noqa: BLE001
            GLib.idle_add(self.append_error, f"{type(exc).__name__}：{exc}", gen)
        finally:
            if gen == self._gen:
                if self._cancel.is_set():
                    GLib.idle_add(self.append_notice, "已停止。", gen)
                GLib.idle_add(self.finish)

    def strip_old_images(self):
        """只保留最新一张截图，旧图换成占位文本，避免上下文越来越大。"""
        for m in self.messages:
            c = m.get("content")
            if isinstance(c, list):
                kept = [p for p in c if p.get("type") != "image_url"]
                m["content"] = kept if kept else "（之前的截图已省略）"

    def trim_history(self):
        if len(self.messages) <= 60:
            return
        cut = len(self.messages) - 60
        while cut < len(self.messages) and self.messages[cut].get("role") != "user":
            cut += 1
        self.messages = self.messages[cut:]

    def finish(self):
        self.busy = False
        if getattr(self, "_status_timer", None):
            GLib.source_remove(self._status_timer)
            self._status_timer = None
        self.status.set_visible(False)
        self.spinner.stop()
        self.spinner.set_visible(False)
        # 干完活把焦点收回输入框，方便接着说话
        if self.win is not None and self.win.get_visible():
            self.win.present()
            self.entry.grab_focus()
        return False

    # ------------------------------------------------------------ 确认框 / 截图钩子

    def confirm(self, title, detail):
        self._confirm_event = threading.Event()
        self._confirm_ok = False
        GLib.idle_add(self._show_confirm, title, detail)
        self._confirm_event.wait()
        return self._confirm_ok

    def _show_confirm(self, title, detail):
        self._awaiting_confirm = True
        self.status.set_text("等待确认")
        self.status.set_visible(True)
        self.confirm_label.set_text(f"{title}\n{detail[:300]}")
        self.confirm_revealer.set_reveal_child(True)
        return False

    def _answer_confirm(self, ok):
        self._awaiting_confirm = False
        if self.busy:
            self.status.set_text("思考中")
        self.confirm_revealer.set_reveal_child(False)
        self._confirm_ok = ok
        if self._confirm_event is not None:
            self._confirm_event.set()

    # ------------------------------------------------------------ 窗口自控

    def request_show(self):
        GLib.idle_add(self.show)

    def request_hide(self):
        GLib.idle_add(self.hide)

    def panel_info(self):
        me = self._my_window()
        layout = (me or {}).get("layout") or {}
        pos = layout.get("tile_pos_in_workspace_view") or [self.geom["x"], self.geom["y"]]
        size = layout.get("window_size") or [self.geom["w"], self.geom["h"]]
        sw, sh = screen_size()
        return {
            "x": int(pos[0]), "y": int(pos[1]),
            "width": int(size[0]), "height": int(size[1]),
            "screen_width": int(sw), "screen_height": int(sh),
            "visible": bool(self.win and self.win.get_visible()),
            "opacity": round(float(self.geom.get("opacity", 1.0)), 2),
        }

    def _apply_panel(self):
        """在主线程应用几何变化。"""
        if self.win is not None:
            self.win.set_opacity(self.geom.get("opacity", 1.0))
            w, h = self.geom["w"], self.geom["h"]
            # 非 resizable 窗口缩小需要先把最小尺寸压到目标以下，
            # 否则 GTK 会保留上一次的较大尺寸。
            if w < self.root.get_width() or h < self.root.get_height():
                self.root.set_size_request(max(1, w - 1), max(1, h - 1))
                GLib.timeout_add(20, self._apply_panel_size)
            else:
                self._apply_panel_size()
        return False

    def _apply_panel_size(self):
        self.root.set_size_request(self.geom["w"], self.geom["h"])
        if self.win is not None and self.win.get_visible():
            threading.Thread(
                target=self._move_to,
                args=(self.geom["x"], self.geom["y"]),
                daemon=True).start()
        return False

    def _schedule_apply(self):
        GLib.idle_add(self._apply_panel)

    def panel_move(self, x, y):
        self.geom["x"], self.geom["y"] = int(x), int(y)
        self._save_geom()
        self._schedule_apply()
        return self.panel_info()

    def panel_resize(self, w, h):
        self.geom["w"], self.geom["h"] = int(w), int(h)
        self._save_geom()
        self._schedule_apply()
        return self.panel_info()

    def panel_set(self, x, y, w, h):
        self.geom.update({"x": int(x), "y": int(y), "w": int(w), "h": int(h)})
        self._save_geom()
        self._schedule_apply()
        return self.panel_info()

    def panel_dock(self, edge, margin=18, size=None):
        sw, sh = screen_size()
        m = int(margin)
        if edge in ("left", "right"):
            w = int(size) if size else self.geom["w"]
            h = min(self.geom["h"], int(sh) - 2 * m)
            x = m if edge == "left" else int(sw) - m - w
            y = (int(sh) - h) // 2
        else:
            h = int(size) if size else self.geom["h"]
            w = min(self.geom["w"], int(sw) - 2 * m)
            y = m if edge == "top" else int(sh) - m - h
            x = (int(sw) - w) // 2
        return self.panel_set(x, y, w, h)

    def panel_opacity(self, value):
        try:
            v = max(0.2, min(1.0, float(value)))
        except (TypeError, ValueError):
            v = 1.0
        self.geom["opacity"] = v
        self._save_geom()
        self._schedule_apply()
        return self.panel_info()

    def panel_reset(self):
        sw, sh = screen_size()
        h = min(PANEL_H_MAX, int(sh) - 2 * MARGIN)
        return self.panel_set(int(sw) - MARGIN - PANEL_W, (int(sh) - h) // 2,
                              PANEL_W, h)

    def hide_for_shot(self):
        """截图时把自己的窗口收起来，避免挡住目标或把自己的文字拍进画面。"""
        self._shot_focus = None
        try:
            for w in list_windows():
                if w.get("is_focused") and w.get("app_id") != APP_ID:
                    self._shot_focus = w["id"]
                    break
        except Exception:  # noqa: BLE001
            pass
        if self.win is not None and self.win.get_visible():
            GLib.idle_add(self._set_visible, False)
            time.sleep(0.08)

    def show_after_shot(self):
        if self.win is not None and not self.win.get_visible() and self.busy:
            GLib.idle_add(self._set_visible, True)
            time.sleep(0.10)
            if getattr(self, "_shot_focus", None):
                run(["niri", "msg", "action", "focus-window",
                     "--id", str(self._shot_focus)], timeout=3)

    def _set_visible(self, value):
        if self.win is not None:
            self.win.set_visible(value)
            if value:
                self.win.present()
        return False

    def park_panel(self, x, y):
        """点击点被自己的面板挡住时，把面板临时挪到角落，点完再挪回来。"""
        if self.win is None or not self.win.get_visible():
            return False
        me = next((w for w in list_windows()
                   if w.get("app_id") == APP_ID), None)
        if not me:
            return False
        layout = me.get("layout") or {}
        pos = layout.get("tile_pos_in_workspace_view") or [0, 0]
        size = layout.get("window_size") or [PANEL_W, PANEL_H_MAX]
        x0, y0 = pos
        w, h = size
        if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h):
            return False
        sw, sh = screen_size()
        target_x = (sw - w - 16) if x < sw / 2 else 16
        target_y = 16
        dx = round(target_x - x0)
        dy = round(target_y - y0)
        run(["niri", "msg", "action", "move-floating-window",
             "--id", str(me["id"]), f"--x={dx:+d}", f"--y={dy:+d}"], timeout=4)
        self._park_delta = (dx, dy)
        time.sleep(0.06)
        return True

    def unpark_panel(self):
        delta = getattr(self, "_park_delta", None)
        if not delta:
            return
        me = next((w for w in list_windows()
                   if w.get("app_id") == APP_ID), None)
        if me:
            dx, dy = delta
            run(["niri", "msg", "action", "move-floating-window",
                 "--id", str(me["id"]), f"--x={-dx:+d}", f"--y={-dy:+d}"], timeout=4)
        self._park_delta = None


def main():
    app = Archlot()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
