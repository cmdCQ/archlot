"""面板内的图形配置向导：教程、模型、外观、Copilot 键。

不另开窗口，也不弹系统对话框；所有页面都在 Archlot 自己的面板里，
和对话共用同一套背景、圆角、透明度和强调色。
"""

from __future__ import annotations

import logging
import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import appearance  # noqa: E402

log = logging.getLogger(__name__)

STEP_NAMES = ("tour", "model", "appearance", "hotkey", "done")
STEP_LABELS = ("教程", "模型", "外观", "快捷键", "完成")
PRESET_LABELS = {
    "default": "默认",
    "midnight": "午夜",
    "warm": "暖色",
    "cyan": "青色",
    "mono": "单色",
    "rose": "玫瑰",
}
ACCENTS = ("#b9a7f5", "#8ab4ff", "#67e8f9", "#f0a868", "#f0a3c8", "#d4d4d8")
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _label(text, css="", wrap=True, xalign=0.0):
    label = Gtk.Label(label=text)
    if css:
        label.add_css_class(css)
    label.set_xalign(xalign)
    label.set_wrap(wrap)
    label.set_wrap_mode(2)  # Pango.WrapMode.WORD_CHAR，不额外 import Pango
    return label


def _valid_hex(text):
    text = str(text or "").strip()
    return bool(_HEX.match(text))


def _same_look(a, b):
    return all(a.get(key) == b.get(key) for key in appearance.FIELDS)


class Onboarding:
    def __init__(self, panel):
        self.panel = panel
        self.step = 0
        self._syncing = False
        self._flush_timer = 0
        self._pending = {}
        self._hotkey_timer = 0
        self._preset_buttons = {}
        self._scrolls = {}
        self._build()

    # ---------------------------------------------------------------- 构建

    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("setup")
        self.widget = root

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("setup-header")
        brand = _label("ARCHLOT", "brand", wrap=False)
        brand.set_hexpand(False)
        self.step_label = _label("1 / 5", "setup-step", wrap=False, xalign=1)
        self.step_label.set_hexpand(True)
        close = Gtk.Button(label="×")
        close.add_css_class("setup-close")
        close.set_tooltip_text("跳过 / 关闭设置")
        close.connect("clicked", lambda *_: self.panel.close_setup())
        header.append(brand)
        header.append(self.step_label)
        header.append(close)
        press = Gtk.GestureClick()
        press.set_button(1)
        press.connect("pressed", self._begin_drag, header)
        header.add_controller(press)
        header.set_cursor_from_name("grab")
        root.append(header)

        self.inner = Gtk.Stack()
        self.inner.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.inner.set_transition_duration(170)
        self.inner.set_vexpand(True)
        self.inner.set_hexpand(True)
        root.append(self.inner)

        self.inner.add_named(self._wrap(self._build_tour(), "tour"), "tour")
        self.inner.add_named(self._wrap(self._build_model(), "model"), "model")
        self.inner.add_named(
            self._wrap(self._build_appearance(), "appearance"), "appearance")
        self.inner.add_named(self._wrap(self._build_hotkey(), "hotkey"), "hotkey")
        self.inner.add_named(self._wrap(self._build_done(), "done"), "done")

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.add_css_class("setup-footer")
        self.back_btn = Gtk.Button(label="上一步")
        self.back_btn.add_css_class("small")
        self.back_btn.connect("clicked", lambda *_: self.back())
        self.dots = _label("", "setup-dots", wrap=False, xalign=0.5)
        self.dots.set_hexpand(True)
        self.next_btn = Gtk.Button(label="下一步")
        self.next_btn.add_css_class("setup-next")
        self.next_btn.connect("clicked", lambda *_: self.next())
        footer.append(self.back_btn)
        footer.append(self.dots)
        footer.append(self.next_btn)
        root.append(footer)

    def _wrap(self, box, name):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        box.set_hexpand(True)
        scroll.set_child(box)
        self._scrolls[name] = scroll
        return scroll

    @staticmethod
    def _page():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.add_css_class("setup-body")
        return box

    @staticmethod
    def _title(text):
        label = _label(text, "setup-title")
        return label

    @staticmethod
    def _sub(text):
        return _label(text, "setup-sub")

    @staticmethod
    def _card():
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("setup-card")
        return card

    def _begin_drag(self, gesture, n_press, x, y, widget):
        self.panel._begin_drag_from(widget, gesture, x, y)

    # ---------------------------------------------------------------- 教程

    def _build_tour(self):
        box = self._page()
        box.append(self._title("先认识一下 Archlot"))
        box.append(self._sub(
            "Archlot 住在桌面右侧，不是网页聊天框。它能看屏幕、动鼠标、"
            "敲键盘、跑命令，也会记住你的习惯和踩过的坑。"))

        mock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        mock.add_css_class("setup-mock")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        top.append(_label("ARCHLOT", "brand", wrap=False))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top.append(spacer)
        top.append(_label("niri", "setup-mock-status", wrap=False))
        mock.append(top)

        user = _label("帮我填一下这个表单", "setup-mock-user")
        user.set_halign(Gtk.Align.END)
        user.set_margin_start(42)
        mock.append(user)
        mock.append(_label("好，我先截图找第一个输入框。", "setup-mock-text"))
        for tool, detail in (
                ("screenshot", "frame 18"),
                ("click", "(32, 597)"),
                ("type_text", '"2130"')):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
            dot = Gtk.Box()
            dot.add_css_class("tool-dot")
            dot.add_css_class("tool-dot-done")
            dot.set_valign(Gtk.Align.CENTER)
            row.append(dot)
            row.append(_label(tool, "setup-mock-tool", wrap=False))
            detail_label = _label(detail, "setup-mock-detail", wrap=False)
            detail_label.set_hexpand(True)
            detail_label.set_xalign(1)
            row.append(detail_label)
            mock.append(row)
        box.append(mock)

        features = self._card()
        features.append(_label("它能做什么", "setup-card-title"))
        for key, text in (
                ("看", "带坐标网格的截图；应用暴露 AT-SPI 时直接读语义树"),
                ("动", "点击、滚动、输入、真实键码、切换窗口"),
                ("干", "跑 shell、读写文件、操作桌面"),
                ("记", "本地 SQLite 长期记忆：偏好、环境、项目、经验")):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            k = _label(key, "setup-feature-key", wrap=False)
            k.set_size_request(24, -1)
            v = _label(text, "setup-feature-text")
            v.set_hexpand(True)
            row.append(k)
            row.append(v)
            features.append(row)
        box.append(features)

        keys = self._card()
        keys.append(_label("基本操作", "setup-card-title"))
        for key, text in (
                ("Enter", "发送"),
                ("Ctrl+L", "清空上下文（长期记忆保留）"),
                ("Esc", "取消任务 / 拒绝确认 / 收起面板"),
                ("拖标题栏", "移动面板"),
                ("Copilot 键", "随时召唤；第 4 步可以帮你绑定")):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            k = _label(key, "kbd", wrap=False)
            k.set_size_request(74, -1)
            v = _label(text, "setup-key-desc")
            v.set_hexpand(True)
            row.append(k)
            row.append(v)
            keys.append(row)
        box.append(keys)

        look = self._card()
        look.append(_label("外观随时能改", "setup-card-title"))
        look.append(_label(
            "直接说“透明一点”“换个青色”“圆角小一点”“字大一点”。"
            "调顺眼了就说“把现在的外观存成默认”，玩坏了说“恢复默认外观”。"
            "下一页有预设和实时调节。", "setup-feature-text"))
        box.append(look)
        return box

    # ---------------------------------------------------------------- 模型

    def _entry(self, text="", placeholder="", password=False):
        entry = Gtk.Entry()
        entry.set_text(text or "")
        entry.set_placeholder_text(placeholder or "")
        entry.set_hexpand(True)
        entry.add_css_class("setup-entry")
        if password:
            entry.set_visibility(False)
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        return entry

    def _field(self, label_text, entry):
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        holder.append(_label(label_text, "setup-label", wrap=False))
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        line.add_css_class("setup-field")
        line.append(entry)
        holder.append(line)
        return holder

    def _build_model(self):
        box = self._page()
        box.append(self._title("连接模型"))
        box.append(self._sub(
            "任何 OpenAI 兼容接口都可以。默认接 DeepSeek，只写本机 "
            "~/.config/archlot/config.json（权限 600）。"))
        info = self.panel.setup_model_info()
        self.base_entry = self._entry(
            info["api_base"], "https://api.deepseek.com")
        key_hint = ("已配置 " + info["api_key_masked"] + "，留空保留"
                    if info["api_key_set"] else "sk-…（也可用 DEEPSEEK_API_KEY）")
        self.key_entry = self._entry("", key_hint, password=True)
        self.model_entry = self._entry(
            info["model"], "deepseek-flash")
        self.workspace_entry = self._entry(
            info["workspace"], "~/archlot-workspace")
        box.append(self._field("API 地址", self.base_entry))
        box.append(self._field("API key", self.key_entry))
        box.append(self._field("模型名", self.model_entry))
        box.append(self._field("工作区", self.workspace_entry))
        self.model_status = _label("", "setup-status")
        box.append(self.model_status)
        saved = self._card()
        saved.append(_label("保存在哪", "setup-card-title"))
        saved.append(_label(
            "key 只在被模型请求时离开本机。改完立即生效，不用重启。"
            "工作区用于 shell 的 cwd 和文件工具的默认目录。",
            "setup-feature-text"))
        box.append(saved)
        return box

    def _refresh_model(self):
        info = self.panel.setup_model_info()
        self.base_entry.set_text(info["api_base"])
        self.model_entry.set_text(info["model"])
        self.workspace_entry.set_text(info["workspace"])
        self.key_entry.set_text("")
        self.key_entry.set_placeholder_text(
            "已配置 " + info["api_key_masked"] + "，留空保留"
            if info["api_key_set"] else "sk-…（也可用 DEEPSEEK_API_KEY）")
        self.model_status.set_text("")

    def _save_model(self):
        result = self.panel.setup_save_model(
            self.base_entry.get_text(), self.key_entry.get_text(),
            self.model_entry.get_text(), self.workspace_entry.get_text())
        if not result.get("ok"):
            self._status(self.model_status, result.get("error", "保存失败"),
                         error=True)
            return False
        self.key_entry.set_text("")
        if result.get("api_key_set"):
            self.key_entry.set_placeholder_text(
                "已配置 " + result["api_key_masked"] + "，留空保留")
            self._status(self.model_status, "已保存，立即生效。")
        else:
            self._status(
                self.model_status,
                "已保存地址和模型，但还没有 key。填好 key 后才能对话。",
                error=True)
        return True

    # ---------------------------------------------------------------- 外观

    def _build_appearance(self):
        box = self._page()
        box.append(self._title("调成你的样子"))
        box.append(self._sub("所有改动立即作用在这块面板上；磨砂模糊由 niri 负责。"))

        preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        preview.add_css_class("setup-preview")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top.append(_label("ARCHLOT", "brand", wrap=False))
        flex = Gtk.Box()
        flex.set_hexpand(True)
        top.append(flex)
        top.append(_label("预览", "setup-mock-status", wrap=False))
        preview.append(top)
        user = _label("透明一点，主色换成青色", "setup-mock-user")
        user.set_halign(Gtk.Align.END)
        user.set_margin_start(32)
        preview.append(user)
        preview.append(_label("好，正在调整外观。", "setup-mock-text"))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        dot = Gtk.Box()
        dot.add_css_class("tool-dot")
        dot.set_valign(Gtk.Align.CENTER)
        row.append(dot)
        row.append(_label("appearance", "setup-mock-tool", wrap=False))
        detail = _label("accent=#67e8f9", "setup-mock-detail", wrap=False)
        detail.set_hexpand(True)
        detail.set_xalign(1)
        row.append(detail)
        preview.append(row)
        box.append(preview)

        info = self.panel.appearance_info()
        box.append(_label("预设", "setup-label", wrap=False))
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)
        for index, name in enumerate(("default", "midnight", "warm",
                                      "cyan", "mono", "rose")):
            button = self._preset_button(name, appearance.PRESETS[name])
            button.connect("clicked", lambda _b, n=name: self._preset(n))
            self._preset_buttons[name] = button
            grid.attach(button, index % 2, index // 2, 1, 1)
        box.append(grid)

        (self.opacity_scale, self.opacity_value,
         opacity_holder) = self._slider(
            "透明度", "opacity", 0.2, 1.0, 0.01, "{:.2f}")
        (self.radius_scale, self.radius_value,
         radius_holder) = self._slider(
            "圆角", "radius", 0.0, 28.0, 1.0, "{:.0f}px", integer=True)
        (self.font_scale, self.font_value,
         font_holder) = self._slider(
            "字号", "font_scale", 0.85, 1.3, 0.01, "{:.2f}×")
        (self.noise_scale, self.noise_value,
         noise_holder) = self._slider(
            "背景噪点", "noise", 0.0, 0.1, 0.005, "{:.3f}")
        for widget in (opacity_holder, radius_holder,
                       font_holder, noise_holder):
            box.append(widget)

        accent_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        accent_row.append(_label("主色", "setup-label", wrap=False))
        for color in ACCENTS:
            swatch = Gtk.Button()
            swatch.add_css_class("setup-swatch")
            swatch.set_tooltip_text(color)
            mark = Gtk.Label()
            mark.set_markup(f'<span foreground="{color}">●</span>')
            swatch.set_child(mark)
            swatch.connect("clicked", lambda _b, c=color: self._accent(c))
            accent_row.append(swatch)
        self.accent_entry = self._entry("", "#b9a7f5")
        self.accent_entry.set_width_chars(8)
        self.accent_entry.set_max_width_chars(8)
        self.accent_entry.connect("activate", self._accent_entry_apply)
        accent_row.append(self.accent_entry)
        box.append(accent_row)

        toggles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.blur_toggle = Gtk.ToggleButton(label="磨砂模糊")
        self.blur_toggle.add_css_class("setup-toggle")
        self.blur_toggle.connect("toggled", self._toggle_visual)
        self.xray_toggle = Gtk.ToggleButton(label="X 光模糊")
        self.xray_toggle.add_css_class("setup-toggle")
        self.xray_toggle.connect("toggled", self._toggle_visual)
        toggles.append(self.blur_toggle)
        toggles.append(self.xray_toggle)
        box.append(toggles)
        box.append(_label(
            "模糊和圆角裁剪由 niri 的 window-rule 执行；下一页可以把当前外观写进 niri。",
            "setup-hint"))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save = Gtk.Button(label="存为默认外观")
        save.add_css_class("setup-next")
        save.connect("clicked", lambda *_: self._save_default())
        restore = Gtk.Button(label="恢复默认")
        restore.add_css_class("small")
        restore.connect("clicked", lambda *_: self._restore_default())
        actions.append(save)
        actions.append(restore)
        box.append(actions)
        self.appearance_status = _label("", "setup-status")
        box.append(self.appearance_status)

        profiles = self._card()
        profiles.append(_label("命名配置", "setup-card-title"))
        profiles.append(_label(
            "想留多套外观就存成名字，例如 work、night、demo。",
            "setup-feature-text"))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.profile_entry = self._entry("", "配置名，例如 work")
        self.profile_entry.connect("activate", lambda *_: self._save_profile())
        save_profile = Gtk.Button(label="保存")
        save_profile.add_css_class("small")
        save_profile.connect("clicked", lambda *_: self._save_profile())
        row.append(self.profile_entry)
        row.append(save_profile)
        profiles.append(row)
        self.profiles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                    spacing=6)
        profiles.append(self.profiles_box)
        box.append(profiles)
        return box

    def _preset_button(self, name, preset):
        button = Gtk.Button()
        button.add_css_class("preset")
        child = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        swatches = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=1)
        for color in (preset["accent"], preset["background"]):
            mark = Gtk.Label()
            mark.set_markup(f'<span foreground="{color}">●</span>')
            swatches.append(mark)
        child.append(swatches)
        text = _label(PRESET_LABELS.get(name, name), "setup-preset-name",
                      wrap=False)
        text.set_hexpand(True)
        text.set_xalign(0)
        child.append(text)
        button.set_child(child)
        return button

    def _slider(self, label_text, field, low, high, step, fmt,
                integer=False):
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.append(_label(label_text, "setup-label", wrap=False))
        value = _label("", "setup-value", wrap=False, xalign=1)
        value.set_hexpand(True)
        top.append(value)
        scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, low, high, step)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.connect("value-changed", self._scale_changed, field, value,
                      fmt, integer)
        holder.append(top)
        holder.append(scale)
        return scale, value, holder

    def _scale_changed(self, scale, field, value_label, fmt, integer):
        value = scale.get_value()
        if integer:
            value = int(round(value))
        else:
            value = round(value, 3)
        value_label.set_text(fmt.format(value))
        if self._syncing:
            return
        self._queue_appearance(**{field: value})

    def _queue_appearance(self, **changes):
        self._pending.update(changes)
        if not self._flush_timer:
            self._flush_timer = GLib.timeout_add(80, self._flush_appearance)

    def _flush_appearance(self):
        self._flush_timer = 0
        pending, self._pending = self._pending, {}
        if pending:
            self.panel.appearance_set(**pending)
            self._mark_preset_active()
        return False

    def _flush_now(self):
        if self._flush_timer:
            GLib.source_remove(self._flush_timer)
            self._flush_timer = 0
        pending, self._pending = self._pending, {}
        if pending:
            self.panel.appearance_set(**pending)
        self._mark_preset_active()

    def _sync_appearance(self):
        info = self.panel.appearance_info()
        self._syncing = True
        try:
            self.opacity_scale.set_value(float(info["opacity"]))
            self.opacity_value.set_text(f"{float(info['opacity']):.2f}")
            self.radius_scale.set_value(float(info["radius"]))
            self.radius_value.set_text(f"{int(info['radius'])}px")
            self.font_scale.set_value(float(info["font_scale"]))
            self.font_value.set_text(f"{float(info['font_scale']):.2f}×")
            self.noise_scale.set_value(float(info["noise"]))
            self.noise_value.set_text(f"{float(info['noise']):.3f}")
            self.blur_toggle.set_active(bool(info["blur"]))
            self.xray_toggle.set_active(bool(info["xray"]))
            self.accent_entry.set_text(str(info["accent"]))
        finally:
            self._syncing = False
        self._mark_preset_active()
        self._refresh_profiles(info)

    def _mark_preset_active(self):
        state = self.panel.appearance_info()
        for name, button in self._preset_buttons.items():
            preset = appearance.normalize(appearance.PRESETS[name])
            if _same_look(state, preset):
                button.add_css_class("active")
            else:
                button.remove_css_class("active")

    def _preset(self, name):
        info = self.panel.appearance_preset(name)
        if info is not None:
            self._sync_appearance()
            self._status(self.appearance_status,
                         f"已套用「{PRESET_LABELS.get(name, name)}」预设。")

    def _accent(self, color):
        self.accent_entry.set_text(color)
        self.panel.appearance_set(accent=color)
        self._status(self.appearance_status, f"主色改为 {color}。")

    def _accent_entry_apply(self, entry):
        text = entry.get_text().strip()
        if not text.startswith("#"):
            text = "#" + text
        if not _valid_hex(text):
            self._status(self.appearance_status,
                         "颜色格式写成 #rrggbb 或 #rgb。", error=True)
            return
        entry.set_text(text.lower())
        self._accent(text.lower())

    def _toggle_visual(self, _button=None):
        if self._syncing:
            return
        self._queue_appearance(blur=self.blur_toggle.get_active(),
                               xray=self.xray_toggle.get_active())

    def _save_default(self):
        self._flush_now()
        info = self.panel.appearance_save()
        if info is None:
            self._status(self.appearance_status, "保存失败。", error=True)
            return
        self._status(self.appearance_status,
                     "已存为默认外观。之后说“恢复默认外观”就能回来。")
        self._refresh_profiles(info)

    def _restore_default(self):
        self._flush_now()
        info = self.panel.appearance_load()
        if info is None:
            self._status(self.appearance_status, "没有可恢复的默认外观。",
                         error=True)
            return
        self._sync_appearance()
        self._status(self.appearance_status, "已恢复默认外观。")

    def _save_profile(self):
        name = self.profile_entry.get_text().strip()
        self._flush_now()
        info = self.panel.appearance_save(name)
        if info is None:
            self._status(self.appearance_status,
                         "配置名留空、太长（超过 24 字）或用了 default。",
                         error=True)
            return
        self.profile_entry.set_text("")
        self._refresh_profiles(info)
        self._status(self.appearance_status, f"已保存外观配置「{name}」。")

    def _refresh_profiles(self, info=None):
        info = info or self.panel.appearance_info()
        while self.profiles_box.get_first_child() is not None:
            self.profiles_box.remove(self.profiles_box.get_first_child())
        names = info.get("profiles") or []
        if not names:
            self.profiles_box.append(
                _label("还没有命名配置。", "setup-hint"))
            return
        for name in names:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            apply_btn = Gtk.Button(label=name)
            apply_btn.add_css_class("setup-profile")
            apply_btn.set_hexpand(True)
            apply_btn.connect("clicked", lambda _b, n=name: self._load_profile(n))
            delete_btn = Gtk.Button(label="删除")
            delete_btn.add_css_class("setup-mini")
            delete_btn.connect("clicked", lambda _b, n=name: self._delete_profile(n))
            row.append(apply_btn)
            row.append(delete_btn)
            self.profiles_box.append(row)

    def _load_profile(self, name):
        info = self.panel.appearance_load(name)
        if info is None:
            self._status(self.appearance_status, "没有这个配置。", error=True)
            return
        self._sync_appearance()
        self._status(self.appearance_status, f"已套用「{name}」。")

    def _delete_profile(self, name):
        info = self.panel.appearance_delete(name)
        if info is None:
            self._status(self.appearance_status, "删除失败。", error=True)
            return
        self._refresh_profiles(info)
        self._status(self.appearance_status, f"已删除「{name}」。")

    # ---------------------------------------------------------------- 快捷键

    def _build_hotkey(self):
        box = self._page()
        box.append(self._title("用 Copilot 键召唤"))
        box.append(self._sub(
            "把 Copilot 键绑到 archlot --toggle：按一下唤出，再按一下收起。"
            "很多笔记本在 Wayland 里把它报成 XF86TouchpadOff。"))
        holder = self._card()
        holder.append(_label("niri 按键组合", "setup-label", wrap=False))
        self.hotkey_entry = self._entry("Mod+Shift+XF86TouchpadOff")
        self.hotkey_entry.connect("changed", self._hotkey_changed)
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        line.add_css_class("setup-field")
        line.append(self.hotkey_entry)
        holder.append(line)
        holder.append(_label(
            "这会在 niri 配置里生成一个 window-rule（圆角/模糊）和一个 binds 块，"
            "并自动备份 config.kdl。", "setup-hint"))
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.hotkey_write_btn = Gtk.Button(label="写入 niri 配置")
        self.hotkey_write_btn.add_css_class("setup-next")
        self.hotkey_write_btn.connect("clicked", lambda *_: self._write_hotkey())
        copy_btn = Gtk.Button(label="复制片段")
        copy_btn.add_css_class("small")
        copy_btn.connect("clicked", lambda *_: self._copy_hotkey())
        actions.append(self.hotkey_write_btn)
        actions.append(copy_btn)
        holder.append(actions)
        self.hotkey_status = _label("", "setup-status")
        holder.append(self.hotkey_status)
        box.append(holder)

        code_card = self._card()
        code_card.append(_label("将写入的内容", "setup-card-title"))
        self.hotkey_code = _label("", "setup-code")
        self.hotkey_code.set_selectable(True)
        self.hotkey_code.set_xalign(0)
        code_card.append(self.hotkey_code)
        box.append(code_card)
        return box

    def _hotkey_changed(self, _entry):
        if self._hotkey_timer:
            GLib.source_remove(self._hotkey_timer)
        self._hotkey_timer = GLib.timeout_add(180, self._refresh_hotkey)

    def _hotkey_block(self):
        text = self.hotkey_entry.get_text().strip()
        if not text:
            return None
        return self.panel.setup_hotkey_info(text)

    def _refresh_hotkey(self):
        self._hotkey_timer = 0
        info = self._hotkey_block()
        if info is None:
            self.hotkey_code.set_text("")
            self._status(self.hotkey_status, "按键组合不能为空。", error=True)
            self.hotkey_write_btn.set_sensitive(False)
            return False
        self.hotkey_code.set_text(info.get("block") or "")
        self.hotkey_write_btn.set_sensitive(
            bool(info["exists"])
            and not (info["mentions"] and not info["managed"]))
        if info.get("error"):
            self._status(self.hotkey_status, "绑定无效：" + info["error"],
                         error=True)
        elif not info["exists"]:
            self._status(
                self.hotkey_status,
                "没找到 " + info["path"] + "。可以复制片段手动加，"
                "或安装 niri 后再回来。", error=True)
        elif info["mentions"] and not info["managed"]:
            self._status(
                self.hotkey_status,
                "niri 配置里已经有 Archlot 的规则或绑定，为避免重复不自动写入。"
                "下面这段可以手动对照。")
        elif info["managed"]:
            self._status(
                self.hotkey_status,
                "已检测到 Archlot 托管块。再次写入会更新外观参数，写前备份。")
        else:
            self._status(self.hotkey_status,
                         "将写入 " + info["path"] + "，写前自动备份。")
        return False

    def _write_hotkey(self):
        self._flush_now()
        result = self.panel.setup_write_hotkey(
            self.hotkey_entry.get_text())
        status = result.get("status")
        if status == "written":
            self._status(
                self.hotkey_status,
                "已写入 niri 配置（备份：" + result.get("backup", "") +
                "）。niri 会自动重载。")
        elif status == "no_config":
            self._status(self.hotkey_status,
                         "没有找到 niri 配置，下面的片段可以手动添加。",
                         error=True)
        elif status == "already_configured":
            self._status(self.hotkey_status,
                         "已有其他 Archlot 配置，未重复写入。", error=True)
        elif status == "invalid":
            self._status(self.hotkey_status,
                         "绑定无效：" + result.get("error", ""), error=True)
        else:
            self._status(self.hotkey_status,
                         "写入失败：" + result.get("error", "未知错误"),
                         error=True)
        self._refresh_hotkey()

    def _copy_hotkey(self):
        info = self._hotkey_block()
        if info is None:
            return
        try:
            display = Gdk.Display.get_default()
            display.get_clipboard().set(info.get("block") or "")
            self._status(self.hotkey_status, "配置片段已复制到剪贴板。")
        except Exception as exc:  # noqa: BLE001
            self._status(self.hotkey_status, f"复制失败：{exc}", error=True)

    # ---------------------------------------------------------------- 完成

    def _build_done(self):
        box = self._page()
        box.append(self._title("可以开始了"))
        box.append(self._sub(
            "设置随时能从右上角 ⚙ 打开。Archlot 现在就是你的桌面搭子。"))
        card = self._card()
        self.done_model = self._done_row(card, "模型")
        self.done_look = self._done_row(card, "外观")
        self.done_hotkey = self._done_row(card, "Copilot 键")
        box.append(card)
        keys = self._card()
        keys.append(_label("记住这几个键", "setup-card-title"))
        keys.append(_label(
            "Enter 发送　·　Ctrl+L 清空上下文　·　Esc 取消/收起　·　"
            "拖标题栏移动面板", "setup-feature-text"))
        box.append(keys)
        again = Gtk.Button(label="再看一遍教程")
        again.add_css_class("small")
        again.set_halign(Gtk.Align.START)
        again.connect("clicked", lambda *_: self.go(0))
        box.append(again)
        return box

    @staticmethod
    def _done_row(card, name):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dot = Gtk.Box()
        dot.add_css_class("tool-dot")
        dot.add_css_class("tool-dot-done")
        dot.set_valign(Gtk.Align.CENTER)
        row.append(dot)
        key = _label(name, "setup-label", wrap=False)
        key.set_size_request(74, -1)
        value = _label("", "setup-feature-text")
        value.set_hexpand(True)
        row.append(key)
        row.append(value)
        card.append(row)
        return value

    def _refresh_done(self):
        cfg = self.panel.cfg
        self.done_model.set_text(
            "已配置" if cfg.api_key else "还没填 key，随时从 ⚙ 补上")
        info = self.panel.appearance_info()
        looks = info.get("profiles") or []
        state = self.panel.appearance_info()
        if all(state.get(k) == info["default"].get(k)
               for k in appearance.FIELDS):
            text = "当前就是已保存的默认外观"
        else:
            text = "当前外观还没存成默认"
        if looks:
            text += f"，另有 {len(looks)} 套命名配置"
        self.done_look.set_text(text)
        hot = self.panel.setup_hotkey_info(self.hotkey_entry.get_text())
        if hot.get("managed"):
            self.done_hotkey.set_text("已写入 niri 配置")
        elif hot.get("mentions"):
            self.done_hotkey.set_text("niri 里已有 Archlot 配置")
        elif hot.get("exists"):
            self.done_hotkey.set_text("还没写入，稍后可以在 ⚙ 里绑定")
        else:
            self.done_hotkey.set_text("没找到 niri 配置，可复制片段手动加")

    # ---------------------------------------------------------------- 导航

    def start(self, page=0):
        self.step = max(0, min(len(STEP_NAMES) - 1, int(page or 0)))
        self.inner.set_visible_child_name(STEP_NAMES[self.step])
        self.refresh()
        self.focus()
        GLib.idle_add(self._scroll_top, self.step)

    def refresh(self):
        if self.step == 1:
            self._refresh_model()
        elif self.step == 2:
            self._sync_appearance()
        elif self.step == 3:
            self._refresh_hotkey()
        elif self.step == 4:
            self._refresh_done()
        self._update_nav()

    def _update_nav(self):
        self.step_label.set_text(f"{self.step + 1} / {len(STEP_NAMES)}")
        self.dots.set_text(" ".join(
            "●" if index <= self.step else "○"
            for index in range(len(STEP_NAMES))))
        self.back_btn.set_visible(self.step > 0)
        self.next_btn.set_label(
            "开始使用" if self.step == len(STEP_NAMES) - 1 else "下一步")
        if self.step == 0:
            self.next_btn.set_label("开始配置")

    def go(self, step):
        self.step = max(0, min(len(STEP_NAMES) - 1, int(step)))
        self.inner.set_visible_child_name(STEP_NAMES[self.step])
        self.refresh()
        self.focus()
        GLib.idle_add(self._scroll_top, self.step)

    def _scroll_top(self, step):
        scroll = self._scrolls.get(STEP_NAMES[step])
        adj = scroll.get_vadjustment() if scroll is not None else None
        if adj is not None:
            adj.set_value(0)
        return False

    def next(self):
        if self.step == 1 and not self._save_model():
            return
        if self.step == 2:
            self._flush_now()
        if self.step >= len(STEP_NAMES) - 1:
            self.panel.close_setup(mark_done=True)
            return
        self.go(self.step + 1)

    def back(self):
        if self.step > 0:
            self.go(self.step - 1)

    def on_key(self, keyval, state):
        if keyval == Gdk.KEY_Escape:
            if self.step > 0:
                self.back()
            else:
                self.panel.close_setup(mark_done=True)
            return True
        focus = self.widget.get_root().get_focus() if self.widget.get_root() else None
        if focus is not None and focus in (
                self.profile_entry, self.hotkey_entry, self.accent_entry):
            return False
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.next()
            return True
        return False

    def focus(self):
        if self.step == 1:
            self.base_entry.grab_focus()
        elif self.step == 3:
            self.hotkey_entry.grab_focus()
        elif self.step == 4:
            self.next_btn.grab_focus()

    @staticmethod
    def _status(label, text, error=False):
        label.set_text(text)
        if error:
            label.add_css_class("setup-error")
        else:
            label.remove_css_class("setup-error")
