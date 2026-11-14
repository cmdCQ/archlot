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
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

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

IDLE_HEIGHT = 66
OPEN_HEIGHT = 560
BOTTOM_MARGIN = 56
WIDTH = 900

SYSTEM_PROMPT = """你是 Archlot，跑在用户 cqsomt 的 Arch Linux + niri 桌面上的私人 AI 助手。

身份：你就是 Archlot。底层模型是 DeepSeek（deepseek-flash，由深度求索提供）。
被问到模型身份时，只回答：我是 Archlot，底层是 DeepSeek 的 deepseek-flash 模型。不要展开猜测。

回答用中文，直接、简短，不要客套话和废话。
输出纯文本：不要用 Markdown 标记（**、#、```、表格竖线），需要强调就用普通句子。

你有真正能干活的工具：执行 shell、读写文件、看屏幕、动鼠标、敲键盘、切窗口。
- 只在真的需要看屏幕或找不着目标位置时才 screenshot；打字、按键后不要为了"确认"再截一张。
- 坐标用最近一张截图的像素坐标。
- 能安全合并的连续动作放在同一轮里一次做完（例如 focus_window + press_key + type_text 一起调用），减少来回；只有结果不确定时才停下来看。
- 危险命令（删除、sudo、关机等）会由程序弹窗让用户确认，你不用反复口头询问。
- 绝不编造工具结果。做不到就直说做不到。
"""


def load_config():
    cfg = {
        "api_base": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "max_tokens": 4096,
        "max_rounds": 8,
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
        self.tools = Tools(self)
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
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("Archlot")
        win.set_decorated(False)
        win.set_default_size(WIDTH, IDLE_HEIGHT)
        win.add_css_class("archlot-window")
        self.add_window(win)
        self.win = win
        win.connect("close-request", lambda *_: (_log("close-request"), True)[1])

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        root.set_size_request(WIDTH, IDLE_HEIGHT)
        win.set_child(root)
        self.root = root

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.set_visible(False)
        root.append(self.scroll)

        self.text = Gtk.TextView()
        self.text.set_editable(False)
        self.text.set_cursor_visible(False)
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.set_top_margin(14)
        self.text.set_bottom_margin(8)
        self.text.set_left_margin(20)
        self.text.set_right_margin(20)
        self.scroll.set_child(self.text)
        self._make_tags()

        # 确认条
        self.confirm_revealer = Gtk.Revealer()
        self.confirm_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        cbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cbox.add_css_class("confirm-bar")
        cbox.set_margin_start(18)
        cbox.set_margin_end(18)
        cbox.set_margin_bottom(6)
        self.confirm_label = Gtk.Label()
        self.confirm_label.set_xalign(0)
        self.confirm_label.set_wrap(True)
        self.confirm_label.set_hexpand(True)
        self.confirm_label.add_css_class("confirm-text")
        cbox.append(self.confirm_label)
        yes = Gtk.Button(label="允许")
        no = Gtk.Button(label="拒绝")
        for b in (yes, no):
            b.add_css_class("small")
            cbox.append(b)
        yes.connect("clicked", lambda *_: self._answer_confirm(True))
        no.connect("clicked", lambda *_: self._answer_confirm(False))
        self.confirm_revealer.set_child(cbox)
        root.append(self.confirm_revealer)

        # 输入条
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.set_margin_start(20)
        bar.set_margin_end(20)
        bar.set_margin_top(12)
        bar.set_margin_bottom(12)
        arrow = Gtk.Label(label="›")
        arrow.add_css_class("arrow")
        self.entry = Gtk.Entry()
        self.entry.set_has_frame(False)
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("问点什么，或者让我去干点什么…")
        self.entry.connect("activate", self.on_send)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        bar.append(arrow)
        bar.append(self.entry)
        bar.append(self.spinner)
        root.append(bar)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

    def _make_tags(self):
        buf = self.text.get_buffer()
        buf.create_tag("user", foreground="#d0bcff", weight=700)
        buf.create_tag("assistant", foreground="#e8e2ec")
        buf.create_tag("tool", foreground="#8e8896", size_points=9)
        buf.create_tag("error", foreground="#f2b8b5")

    # ------------------------------------------------------------ 显示/隐藏

    def show(self):
        _log("show")
        self.ensure_ui()
        self.win.present()
        self.entry.grab_focus()
        GLib.timeout_add(90, self.relocate)

    def hide(self):
        _log("hide")
        if self.win is not None:
            self.win.set_visible(False)

    def toggle(self):
        _log(f"toggle visible={self.win.get_visible() if self.win else None}")
        if self.win is not None and self.win.get_visible() and self.win.is_active():
            self.hide()
        else:
            self.show()

    def on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if self._confirm_event is not None and not self._confirm_event.is_set():
                self._answer_confirm(False)
            else:
                self.hide()
            return True
        if keyval == Gdk.KEY_l and (state & Gdk.ModifierType.CONTROL_MASK):
            self.clear()
            return True
        return False

    def set_expanded(self, expanded):
        if self.win is None:
            return
        self.scroll.set_visible(expanded)
        # GTK4 里窗口已显示后 set_default_size 不生效，用子控件最小尺寸驱动
        self.root.set_size_request(WIDTH, OPEN_HEIGHT if expanded else IDLE_HEIGHT)
        GLib.timeout_add(150, self.relocate)

    def relocate(self):
        """把浮窗钉在屏幕底部居中（后台线程，避免卡住界面）。"""
        if not getattr(self, "_reloc_lock", None):
            self._reloc_lock = threading.Lock()
        if not self._reloc_lock.acquire(blocking=False):
            return False
        threading.Thread(target=self._relocate_worker, daemon=True).start()
        return False

    def _relocate_worker(self):
        try:
            self._relocate_once()
        finally:
            self._reloc_lock.release()

    def _relocate_once(self):
        me = None
        for w in list_windows():
            if w.get("app_id") == APP_ID:
                me = w
                break
        if not me:
            return False
        layout = me.get("layout") or {}
        pos = layout.get("tile_pos_in_workspace_view")
        size = layout.get("window_size") or layout.get("tile_size")
        if not pos or not size:
            return False
        sw, sh = screen_size()
        target_x = (sw - size[0]) / 2
        target_y = sh - size[1] - BOTTOM_MARGIN
        dx = round(target_x - pos[0])
        dy = round(target_y - pos[1])
        if abs(dx) >= 1 or abs(dy) >= 1:
            run(
                ["niri", "msg", "action", "move-floating-window",
                 "--id", str(me["id"]), f"--x={dx:+d}", f"--y={dy:+d}"],
                timeout=4,
            )
        return False

    def clear(self):
        self.messages = []
        self.text.get_buffer().set_text("")
        self.set_expanded(False)

    # ------------------------------------------------------------ 对话

    def on_send(self, entry):
        if self.busy:
            return
        text = entry.get_text().strip()
        if not text:
            return
        entry.set_text("")
        self.busy = True
        self.spinner.set_visible(True)
        self.spinner.start()
        self.append_user(text)
        self.set_expanded(True)
        threading.Thread(target=self.run_agent, args=(text,), daemon=True).start()

    def run_agent(self, text):
        self.messages.append({"role": "user", "content": text})
        try:
            for _ in range(int(self.cfg.get("max_rounds", 8))):
                payload = [{"role": "system", "content": SYSTEM_PROMPT}] + self.messages
                _t0 = time.time()
                msg, _finish = llm.stream_chat(
                    self.cfg, payload, TOOLS,
                    on_text=lambda t: GLib.idle_add(self.append_assistant, t),
                )
                _log(f"llm {time.time() - _t0:.2f}s")
                self.messages.append(msg)
                calls = msg.get("tool_calls")
                if not calls:
                    break
                pending_images = []
                for tc in calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    GLib.idle_add(self.note_tool, name, args)
                    _t1 = time.time()
                    result = self.tools.execute(name, args)
                    _log(f"tool {name} {time.time() - _t1:.2f}s")
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result["text"],
                    })
                    GLib.idle_add(self.note_result, result["text"])
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
            GLib.idle_add(self.append_error, str(exc))
        except Exception as exc:  # noqa: BLE001
            GLib.idle_add(self.append_error, f"{type(exc).__name__}：{exc}")
        finally:
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
        self.spinner.stop()
        self.spinner.set_visible(False)
        # 干完活把焦点收回输入框，方便接着说话
        if self.win is not None and self.win.get_visible():
            self.win.present()
            self.entry.grab_focus()
        return False

    # ------------------------------------------------------------ 文本渲染

    def _insert(self, s, tag=None):
        buf = self.text.get_buffer()
        it = buf.get_end_iter()
        if tag:
            buf.insert_with_tags_by_name(it, s, tag)
        else:
            buf.insert(it, s)
        GLib.idle_add(self._scroll_bottom)

    def _scroll_bottom(self):
        adj = self.scroll.get_vadjustment()
        if adj is not None:
            adj.set_value(adj.get_upper())
        return False

    def append_user(self, text):
        self._insert("\n\n你\n", "user")
        self._insert(text + "\n", "user")

    def append_assistant(self, text):
        text = text.replace("`", "").replace("**", "")
        self._insert(text, "assistant")
        return False

    def note_tool(self, name, args):
        brief = json.dumps(args, ensure_ascii=False)
        if len(brief) > 90:
            brief = brief[:90] + "…"
        self._insert(f"\n  ⚙ {name} {brief}\n", "tool")
        return False

    def note_result(self, text):
        first = (text or "").strip().splitlines()
        line = first[0] if first else ""
        if len(line) > 110:
            line = line[:110] + "…"
        self._insert(f"  ↳ {line}\n", "tool")
        return False

    def append_error(self, text):
        self._insert(f"\n⚠ {text}\n", "error")
        return False

    # ------------------------------------------------------------ 确认框 / 截图钩子

    def confirm(self, title, detail):
        self._confirm_event = threading.Event()
        self._confirm_ok = False
        GLib.idle_add(self._show_confirm, title, detail)
        self._confirm_event.wait()
        return self._confirm_ok

    def _show_confirm(self, title, detail):
        self.confirm_label.set_text(f"{title}\n{detail[:300]}")
        self.confirm_revealer.set_reveal_child(True)
        self.set_expanded(True)
        GLib.timeout_add(140, self.relocate)
        return False

    def _answer_confirm(self, ok):
        self.confirm_revealer.set_reveal_child(False)
        self._confirm_ok = ok
        if self._confirm_event is not None:
            self._confirm_event.set()
        GLib.timeout_add(140, self.relocate)

    def hide_for_shot(self):
        """截图时保留窗口（隐藏会抢走焦点、关掉菜单），不做事。"""

    def show_after_shot(self):
        pass


def main():
    app = Archlot()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
