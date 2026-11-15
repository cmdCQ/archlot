"""通用桌面可访问层：AT-SPI 快照 + 语义动作。

这是 tools/ 里唯一允许 import gi 的模块，而且只 import Atspi：
不创建 GTK 控件、不碰主线程，只在 worker 线程里调用。
目标是给“有可访问性树”的原生应用和浏览器一个精确层；
没有树时明确退回 screenshot + 坐标，不要假装成功。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from core import system
from core.contracts import ToolResult, fail, ok
from . import desktop

log = logging.getLogger(__name__)

try:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    AVAILABLE = True
    IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001
    Atspi = None
    AVAILABLE = False
    IMPORT_ERROR = str(exc)


MAX_NODES = 260
MAX_DEPTH = 40
SNAP_HISTORY = 4

# 角色名在不同工具包里不完全一致（GTK 用 push button，Firefox 用 button）。
INTERACTIVE = {
    "button", "push button", "toggle button", "entry", "text", "password text",
    "check box", "radio button", "combo box", "menu item", "list item",
    "option", "page tab", "tab", "link", "slider", "spin button",
    "table cell", "tree item", "scroll bar",
}
TEXT_ROLES = {
    "entry", "text", "password text", "label", "heading", "link", "button",
    "push button", "toggle button", "check box", "radio button", "menu item",
    "list item", "option", "static text", "paragraph", "table cell",
}
DISABLE_MARK_ROLES = {
    "button", "push button", "toggle button", "entry", "text", "password text",
    "check box", "radio button", "combo box", "menu item", "link", "page tab",
    "tab", "slider", "spin button", "tree item",
}
PREFERRED_ACTIONS = (
    "press", "click", "activate", "jump", "open", "select", "toggle",
    "check", "switch", "default",
)
OPEN_ACTIONS = ("open", "press", "click", "activate")


@dataclass
class Node:
    ref: str
    accessible: object
    frame: object
    window: dict
    role: str
    name: str
    snap: int
    path: tuple = ()


@dataclass
class Snap:
    id: int
    frame: object
    window: dict
    refs: dict[str, Node] = field(default_factory=dict)


# ---------------------------------------------------------------- AT-SPI 小工具

def _call(obj, method, *args, default=None):
    fn = getattr(obj, method, None)
    if fn is None:
        return default
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        return default


def _role(node):
    return (_call(node, "get_role_name", default="") or "").strip()


def _name(node):
    return (_call(node, "get_name", default="") or "").strip()


def _state(node):
    return _call(node, "get_state_set")


def _has_state(node, name):
    st = _state(node)
    if st is None:
        return False
    try:
        return bool(st.contains(getattr(Atspi.StateType, name)))
    except Exception:  # noqa: BLE001
        return False


def _showing(node):
    st = _state(node)
    if st is None:
        return True
    try:
        return bool(st.contains(Atspi.StateType.SHOWING))
    except Exception:  # noqa: BLE001
        return True


def _children(node, limit=500):
    n = _call(node, "get_child_count", default=0) or 0
    for i in range(min(int(n), limit)):
        child = _call(node, "get_child_at_index", i)
        if child is not None:
            yield child


def _action_items(node):
    ai = _call(node, "get_action_iface")
    if ai is None:
        return []
    items = []
    for i in range(_call(ai, "get_n_actions", default=0) or 0):
        name = (_call(ai, "get_action_name", i, default="") or "").strip()
        items.append((name, i))
    return items


def _meaningful_actions(items):
    out = []
    for name, _ in items:
        low = name.lower()
        tail = low.split(".")[-1]
        if (low in ("clickancestor", "scroll-to", "scrollto")
                or tail in ("clickancestor", "scroll-to", "scrollto")):
            continue
        if low not in out and tail not in out:
            out.append(low if not low.startswith("listitem.") else tail)
    return out


def _do_action(node, wanted=PREFERRED_ACTIONS):
    items = _action_items(node)
    if not items:
        return False, ""
    for want in wanted:
        for name, idx in items:
            low = name.lower()
            tail = low.split(".")[-1]
            if low == want or tail == want:
                ai = _call(node, "get_action_iface")
                if ai is not None and _call(ai, "do_action", idx, default=False):
                    return True, name
    return False, ""


def _text_iface(node):
    return _call(node, "get_text_iface")


def _is_password(node):
    return "password" in _role(node).lower()


def _read_text(node, limit=400):
    if _is_password(node):
        return None
    ti = _text_iface(node)
    if ti is not None:
        count = _call(Atspi.Text, "get_character_count", node, default=0) or 0
        if count > 0:
            text = _call(Atspi.Text, "get_text", node, 0,
                         min(int(count), limit))
            if isinstance(text, str):
                return text
    vi = _call(node, "get_value_iface")
    if vi is not None:
        value = _call(vi, "get_current_value")
        if value is not None:
            try:
                return str(value)
            except Exception:  # noqa: BLE001
                pass
    return ""


def _selected_label(node):
    """在 combo/list 里找 STATE_SELECTED 的子项；隐藏的选中项也算。"""
    node = getattr(node, "accessible", node)
    for child in _children(node):
        if _has_state(child, "SELECTED"):
            label = _name(child) or _read_text(child) or ""
            if label:
                return label
        label = _selected_label(child)
        if label:
            return label
    return ""


def _window_pos(window):
    layout = (window or {}).get("layout") or {}
    pos = layout.get("tile_pos_in_workspace_view")
    if pos and len(pos) >= 2:
        return float(pos[0]), float(pos[1])
    return None


def _screen_point(node):
    """取元素中心点，返回 (x, y) 或 None。优先用窗口局部坐标 + niri 位置。"""
    acc = getattr(node, "accessible", node)
    window = getattr(node, "window", None) or {}
    ci = _call(acc, "get_component_iface")
    if ci is None:
        return None
    sw, sh = system.screen_size()

    def center(rect, off_x=0.0, off_y=0.0):
        if rect is None:
            return None
        try:
            x, y = float(rect.x), float(rect.y)
            w, h = float(rect.width), float(rect.height)
        except Exception:  # noqa: BLE001
            return None
        if w <= 0 or h <= 0:
            return None
        x, y = x + off_x, y + off_y
        if not (-2 <= x <= sw + 2 and -2 <= y <= sh + 2):
            return None
        return min(max(0.0, x + w / 2), sw - 1.0), min(max(0.0, y + h / 2), sh - 1.0)

    pos = _window_pos(window)
    if pos is not None:
        rect = _call(ci, "get_extents", Atspi.CoordType.WINDOW)
        point = center(rect, pos[0], pos[1])
        if point:
            return point
    rect = _call(ci, "get_extents", Atspi.CoordType.SCREEN)
    return center(rect)


def _match_window(spec):
    wins = system.list_windows()
    if spec is None or str(spec).strip() == "":
        return next((w for w in wins if w.get("is_focused")), None)
    needle = str(spec).strip().lower()
    for w in wins:
        if str(w.get("id")) == needle:
            return w
    for w in wins:
        if needle == (w.get("app_id") or "").lower():
            return w
    for w in wins:
        if needle in (w.get("app_id") or "").lower():
            return w
    for w in wins:
        if needle in (w.get("title") or "").lower():
            return w
    return None


def _session_enabled():
    """AT-SPI 会话总开关；None 表示查不到。"""
    rc, out, _ = system.run(
        ["gdbus", "call", "--session", "--dest", "org.a11y.Bus",
         "--object-path", "/org/a11y/bus",
         "--method", "org.freedesktop.DBus.Properties.Get",
         "org.a11y.Status", "IsEnabled"], timeout=2)
    if rc != 0:
        return None
    return "true" in out.lower()


def _frames():
    desktop = Atspi.get_desktop(0)
    out = []
    for app in _children(desktop):
        app_name = _name(app)
        for child in _children(app):
            role = _role(child)
            if role in ("frame", "dialog", "window", "alert"):
                out.append((app_name, child))
    return out


def _frame_for(window):
    if not window:
        return None
    title = (window.get("title") or "").strip().lower()
    app_id = (window.get("app_id") or "").strip().lower()
    frames = _frames()
    if not frames:
        return None
    if title:
        matches = [frame for _, frame in frames
                   if _name(frame).lower() == title]
        if len(matches) == 1:
            return matches[0]
        if matches and app_id:
            same_title = [frame for app_name, frame in frames
                          if frame in matches
                          and (app_name or "").lower() == app_id]
            if len(same_title) == 1:
                return same_title[0]
        if matches:
            return None
    if not app_id:
        return None
    # 只在“这个 app 只有一个 niri 窗口、也只有一个 frame”时按 app 兜底。
    # Firefox 同时开着多个窗口时，绝不能把别的窗口的 frame 当成当前窗口。
    same_app = [w for w in system.list_windows()
                if (w.get("app_id") or "").strip().lower() == app_id]
    app_frames = [(app_name, frame) for app_name, frame in frames
                  if (app_name or "").strip().lower() == app_id]
    if len(same_app) == 1 and len(app_frames) == 1:
        return app_frames[0][1]
    return None


def _fresh(node):
    """动作后旧 AT-SPI 代理可能失效；按保存的路径重新取当前对象。"""
    frame = _frame_for(node.window) or node.frame
    if frame is None:
        return node.accessible
    cur = frame
    for idx in node.path:
        child = _call(cur, "get_child_at_index", idx)
        if child is None:
            break
        cur = child
    else:
        if _role(cur) == node.role and _name(cur) == node.name:
            return cur
    # 路径变了（弹层、重排）时退回到 role + name；同名元素已有路径优先。
    stack = [(frame, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth <= 50 and _role(cur) == node.role and _name(cur) == node.name:
            return cur
        if depth < 50:
            kids = list(_children(cur))
            for child in reversed(kids):
                stack.append((child, depth + 1))
    return node.accessible


def _read_after(node, expected=None, tries=5):
    fresh = _fresh(node)
    value = _read_text(fresh)
    for _ in range(max(0, tries - 1)):
        if expected is not None and value == expected:
            break
        time.sleep(0.08)
        fresh = _fresh(node)
        value = _read_text(fresh)
    return fresh, value


# ---------------------------------------------------------------- 快照

def _quote(text, limit=100):
    text = str(text or "").replace("\n", " ").replace("\r", " ")
    text = text.replace('"', "'")
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def _node_value(node, role, name):
    if _is_password(node):
        return "<redacted>"
    if role == "combo box":
        text = _selected_label(node) or _read_text(node)
    else:
        text = _read_text(node)
    if text and role not in ("entry", "text", "password text"):
        text = text.replace("￼", "").replace("�", "").strip()
    if text and text != name:
        return text
    return ""


def _snapshot_text(snap):
    lines = [f"snap={snap.id} window={snap.window.get('app_id')}："
             f"{_quote(snap.window.get('title'), 80)} (id={snap.window.get('id')})"]
    count = 0

    def walk(node, depth, indent, path=()):
        nonlocal count
        if count >= MAX_NODES or depth > MAX_DEPTH:
            return
        if not _showing(node):
            return
        role = _role(node)
        name = _name(node)
        actions = _meaningful_actions(_action_items(node))
        value = _node_value(node, role, name) if role in TEXT_ROLES or role == "combo box" else ""
        keep = (bool(name) or bool(value) or role in INTERACTIVE
                or bool(actions))
        if depth == 0:
            keep = True
        if keep:
            count += 1
            ref = f"e{count}"
            line = f"{indent}{ref} {role or 'node'}"
            if name:
                line += f' "{_quote(name)}"'
            if value:
                line += f' value="{_quote(value, 80)}"'
            marks = []
            if _has_state(node, "CHECKED"):
                marks.append("checked")
            elif _has_state(node, "SELECTED"):
                marks.append("selected")
            if _has_state(node, "EXPANDED"):
                marks.append("expanded")
            if role in DISABLE_MARK_ROLES and not _has_state(node, "ENABLED"):
                marks.append("disabled")
            if marks:
                line += " [" + ",".join(marks) + "]"
            if actions:
                line += " [" + ",".join(actions[:4]) + "]"
            lines.append(line)
            snap.refs[ref] = Node(ref, node, snap.frame, snap.window,
                                  role, name, snap.id, path)
            next_depth, next_indent = depth + 1, indent + "  "
        else:
            next_depth, next_indent = depth, indent
        for idx, child in enumerate(_children(node)):
            walk(child, next_depth, next_indent, path + (idx,))

    walk(snap.frame, 0, "  ")
    if count >= MAX_NODES:
        lines.append("  …（节点过多已截断；可用 window 指定窗口或直接操作已知元素）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 动作

class A11y:
    def __init__(self):
        self._snap_seq = 0
        self._snaps: dict[int, Snap] = {}
        self._latest: int | None = None
        self._inited = False

    def begin_turn(self):
        self._snaps.clear()
        self._latest = None

    def _ensure(self):
        if not AVAILABLE:
            raise RuntimeError(f"AT-SPI 不可用：{IMPORT_ERROR}")
        if not self._inited:
            try:
                Atspi.init()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"AT-SPI 初始化失败：{exc}") from exc
            self._inited = True

    def _get_snap(self, value):
        if value is None:
            sid = self._latest
        else:
            try:
                sid = int(value)
            except (TypeError, ValueError):
                sid = None
        return self._snaps.get(sid) if sid is not None else None

    def _resolve(self, snap_value, ref_value):
        snap = self._get_snap(snap_value)
        if snap is None:
            return None, None, fail(
                "还没有可用的 ui snapshot，或 snap 已过期；先 ui(action=\"snapshot\")。",
                "stale_ref")
        ref = str(ref_value or "").strip()
        if ref.isdigit():
            ref = "e" + ref
        node = snap.refs.get(ref)
        if node is None:
            return None, None, fail(
                f"ref={ref or '?'} 不在 snap={snap.id} 里；重新 snapshot 后再操作。",
                "stale_ref")
        return snap, node, None

    def _focus_window(self, window):
        if not window or window.get("is_focused"):
            return True
        rc, _, _ = system.run(
            ["niri", "msg", "action", "focus-window", "--id",
             str(window.get("id"))], timeout=5)
        time.sleep(0.06)
        return rc == 0

    def _grab_focus(self, node):
        ci = _call(node.accessible, "get_component_iface")
        if ci is None:
            return False
        return bool(_call(ci, "grab_focus", default=False))

    def _focus_node(self, tools, node):
        """键盘输入前必须确认焦点在目标上，不能把字打进别的窗口。"""
        if self._grab_focus(node):
            return True
        if _do_action(node.accessible, ("activate", "click", "press"))[0]:
            time.sleep(0.06)
            return True
        point = _screen_point(node)
        if point is not None:
            tools.mouse.click(point[0], point[1])
            time.sleep(0.1)
            return True
        return False

    def _find_toggle(self, node, depth=0):
        """原生 GTK 的 combo 往往要按它旁边的 toggle button 才能展开。"""
        if depth > 2:
            return None
        for child in _children(getattr(node, "accessible", node)):
            role = _role(child)
            if role in ("toggle button", "button"):
                actions = _meaningful_actions(_action_items(child))
                if actions:
                    return child
            found = self._find_toggle(child, depth + 1)
            if found is not None:
                return found
        return None

    def _open_combo(self, tools, node):
        self._focus_window(node.window)
        if self._grab_focus(node):
            return True
        if _do_action(node.accessible, OPEN_ACTIONS)[0]:
            return True
        toggle = self._find_toggle(node)
        if toggle is not None and _do_action(toggle, OPEN_ACTIONS)[0]:
            return True
        point = _screen_point(node)
        if point:
            tools.mouse.click(point[0], point[1])
            time.sleep(0.12)
            return True
        return False

    def snapshot(self, tools, a):
        self._ensure()
        window = _match_window(a.get("window"))
        if window is None:
            return fail("没找到这个窗口；先 list_windows 看看。", "not_found")
        frame = _frame_for(window)
        if frame is None:
            enabled = _session_enabled()
            if enabled is False:
                why = ("当前会话的 AT-SPI 总开关是关闭的"
                       "（org.a11y.Status.IsEnabled=false），"
                       "大多数应用不会暴露树；先在系统辅助功能里打开。")
            elif enabled:
                why = ("这个窗口没有挂到可访问性树；Firefox 需要"
                       " accessibility.force_enabled=true，"
                       "或用 GNOME_ACCESSIBILITY=1 启动。")
            else:
                why = "这个窗口没有暴露可访问性树。"
            return ok(
                f"窗口 {window.get('app_id')}「{window.get('title')}」"
                f"没有可用可访问性树。{why}不要猜 ref，改用 screenshot 看屏幕。",
                meta={"kind": "observe", "available": False,
                      "a11y_session": enabled, "window": window.get("id")})
        self._snap_seq += 1
        snap = Snap(self._snap_seq, frame, window)
        text = _snapshot_text(snap)
        self._snaps[snap.id] = snap
        self._latest = snap.id
        for old in sorted(self._snaps)[:-SNAP_HISTORY]:
            del self._snaps[old]
        return ok(text + "\n\nref 只在本次 snapshot 有效；动作后用 read 或重新 snapshot 验证。",
                  meta={"kind": "observe", "snap": snap.id,
                        "window": window.get("id")})

    def apps(self, tools, a):
        self._ensure()
        enabled = _session_enabled()
        head = ("AT-SPI 会话：开启" if enabled else
                "AT-SPI 会话：关闭（org.a11y.Status.IsEnabled=false）"
                if enabled is False else "AT-SPI 会话：状态未知")
        lines = [head]
        for app in _children(Atspi.get_desktop(0)):
            child_count = _call(app, "get_child_count", default=0) or 0
            frames = []
            for child in _children(app):
                if _role(child) in ("frame", "dialog", "window", "alert"):
                    frames.append(f"{_role(child)}:{_quote(_name(child), 60)}")
            lines.append(f"{_quote(_name(app), 60)} children={child_count} "
                         + (" ".join(frames) if frames else "(无 frame)"))
        return ok("\n".join(lines),
                  meta={"kind": "observe", "a11y_session": enabled})

    def click(self, tools, a):
        snap, node, err = self._resolve(a.get("snap"), a.get("ref"))
        if err:
            return err
        self._focus_window(node.window)
        done, action = _do_action(node.accessible)
        if done:
            return ok(f"已通过可访问性动作 {action} 点击 {node.ref} "
                      f"{node.role}「{node.name}」；动作已发出，关键操作后请截图确认。",
                      meta={"kind": "act", "effect": "sent", "snap": snap.id})
        point = _screen_point(node)
        if point is None:
            return fail(
                f"{node.ref} 没有可用动作，也拿不到屏幕坐标；"
                "改用 screenshot 找到位置后 click。", "not_actionable",
                meta={"kind": "act", "effect": "failed", "snap": snap.id})
        tools.mouse.click(point[0], point[1])
        return ok(f"已按坐标点击 {node.ref} {node.role}「{node.name}」"
                  f" ({int(point[0])}, {int(point[1])})；只是事件已发出。",
                  meta={"kind": "act", "effect": "sent", "snap": snap.id})

    def focus(self, tools, a):
        snap, node, err = self._resolve(a.get("snap"), a.get("ref"))
        if err:
            return err
        self._focus_window(node.window)
        if self._grab_focus(node):
            return ok(f"已聚焦 {node.ref} {node.role}「{node.name}」",
                      meta={"kind": "act", "effect": "confirmed", "snap": snap.id})
        done, action = _do_action(node.accessible, OPEN_ACTIONS)
        if done:
            return ok(f"已通过动作 {action} 聚焦/展开 {node.ref}「{node.name}」",
                      meta={"kind": "act", "effect": "sent", "snap": snap.id})
        return fail(f"{node.ref} 不支持聚焦；改用 screenshot + click。",
                    "not_actionable",
                    meta={"kind": "act", "effect": "failed", "snap": snap.id})

    def read(self, tools, a):
        snap, node, err = self._resolve(a.get("snap"), a.get("ref"))
        if err:
            return err
        fresh = _fresh(node)
        value = _read_text(fresh)
        if value is None:
            value = "<密码字段，已隐藏>"
        if not value and node.role == "combo box":
            value = _selected_label(fresh)
        if not value:
            value = _name(fresh)
        if not value:
            desc = _call(fresh, "get_description", default="") or ""
            value = desc or "（空）"
        return ok(f"{node.ref} {node.role}「{node.name}」：{value}",
                  meta={"kind": "observe", "snap": snap.id})

    def set_text(self, tools, a):
        snap, node, err = self._resolve(a.get("snap"), a.get("ref"))
        if err:
            return err
        if "text" not in a:
            return fail("缺少 text", "bad_args")
        text = str(a.get("text") or "")
        self._focus_window(node.window)
        focused = self._focus_node(tools, node)
        password = _is_password(node)
        editable = _call(node.accessible, "get_editable_text_iface")
        if editable is not None:
            try:
                edited = bool(Atspi.EditableText.set_text_contents(
                    node.accessible, text))
            except Exception:  # noqa: BLE001
                edited = False
            if edited:
                fresh, after = _read_after(node, text)
                if after is None:
                    return ok(f"已设置 {node.ref}「{node.name}」的内容"
                              "（密码字段无法回读，未确认）。",
                              meta={"kind": "act", "effect": "sent",
                                    "snap": snap.id})
                if after == text:
                    return ok(f"已设置 {node.ref}「{node.name}」"
                              f"并回读确认内容。",
                              meta={"kind": "act", "effect": "confirmed",
                                    "snap": snap.id})
        # Firefox 等应用的 EditableText 会返回 True 但不改值，必须走键盘。
        if not focused:
            return fail(f"无法把焦点放到 {node.ref}「{node.name}」，"
                        "不冒险向其他窗口输入；改用 screenshot 后 click 再 type_text。",
                        "not_actionable",
                        meta={"kind": "act", "effect": "failed",
                              "snap": snap.id})
        r = desktop.press_key(tools, {"keys": "ctrl+a"})
        if not r.ok:
            return fail(f"全选输入框内容失败：{r.text}", "input",
                        meta={"kind": "act", "effect": "failed",
                              "snap": snap.id})
        r = desktop.type_text(tools, {"text": text})
        if not r.ok:
            return r
        fresh, after = _read_after(node, text)
        if after is None:
            return ok(f"已向 {node.ref}「{node.name}」输入内容"
                      "（密码字段无法回读，未确认）。",
                      meta={"kind": "act", "effect": "sent", "snap": snap.id})
        if after == text:
            return ok(f"已输入 {node.ref}「{node.name}」并回读确认。",
                      meta={"kind": "act", "effect": "confirmed",
                            "snap": snap.id})
        if password:
            return ok(f"已向密码字段 {node.ref} 输入内容；无法回读确认。",
                      meta={"kind": "act", "effect": "sent", "snap": snap.id})
        return fail(f"输入后回读不一致：{node.ref} 现在是「{_quote(after, 80)}」",
                    "input",
                    meta={"kind": "act", "effect": "failed", "snap": snap.id})

    def _options(self, node):
        out, seen = [], set()
        node = getattr(node, "accessible", node)

        def walk(cur, depth=0):
            if depth > 6:
                return
            for child in _children(cur):
                role = _role(child)
                if role in ("menu item", "list item", "option", "radio button"):
                    label = _name(child) or _read_text(child) or ""
                    if not label:
                        for sub in _children(child):
                            label = _name(sub) or _read_text(sub) or ""
                            if label:
                                break
                    key = (label.casefold(), id(child))
                    if label and key not in seen:
                        seen.add(key)
                        out.append((label, child,
                                    _has_state(child, "SELECTED")))
                walk(child, depth + 1)

        walk(node)
        return out

    def select(self, tools, a):
        snap, node, err = self._resolve(a.get("snap"), a.get("ref"))
        if err:
            return err
        wanted = str(a.get("option", "")).strip()
        if not wanted:
            return fail("缺少 option", "bad_args")
        options = self._options(_fresh(node))
        if not options:
            return fail(f"{node.ref} 里没有找到可选项；先 read 或 snapshot 看看。",
                        "not_found",
                        meta={"kind": "act", "effect": "failed",
                              "snap": snap.id})
        target = next((o for o in options
                       if o[0].casefold() == wanted.casefold()), None)
        if target is None:
            target = next((o for o in options
                           if wanted.casefold() in o[0].casefold()), None)
        if target is None:
            names = "、".join(o[0] for o in options[:12])
            return fail(f"{node.ref} 没有选项「{wanted}」；可选：{names}",
                        "not_found",
                        meta={"kind": "act", "effect": "failed",
                              "snap": snap.id})
        label, option, _ = target
        index = next(i for i, o in enumerate(options) if o[1] is option)

        self._focus_window(node.window)
        # 先试原生 Selection/Action；Firefox 的 select 动作会假成功，
        # 所以必须回读选中项，不成功就改用键盘。
        if _do_action(option, ("select", "click", "press"))[0]:
            time.sleep(0.08)
            if _selected_label(_fresh(node)).casefold() == label.casefold():
                return ok(f"已选择 {node.ref}「{node.name}」→「{label}」",
                          meta={"kind": "act", "effect": "confirmed",
                                "snap": snap.id})

        if not self._open_combo(tools, node):
            return fail(f"无法聚焦或展开 {node.ref}「{node.name}」；"
                        "改用 screenshot + 键盘选择。", "not_actionable",
                        meta={"kind": "act", "effect": "failed",
                              "snap": snap.id})
        keys = ["Home"] + ["Down"] * index + ["Return"]
        for key in keys:
            r = desktop.press_key(tools, {"keys": key})
            if not r.ok:
                return fail(f"选择「{label}」时按键 {key} 失败：{r.text}",
                            "input",
                            meta={"kind": "act", "effect": "failed",
                                  "snap": snap.id})
            time.sleep(0.02)
        time.sleep(0.15)
        now = _selected_label(_fresh(node))
        if now.casefold() == label.casefold():
            return ok(f"已选择 {node.ref}「{node.name}」→「{label}」并回读确认。",
                      meta={"kind": "act", "effect": "confirmed",
                            "snap": snap.id})
        return fail(f"选择后回读为「{now or '空'}」，不是「{label}」；"
                    "可能被弹层或焦点变化打断，重新截图确认。",
                    "input",
                    meta={"kind": "act", "effect": "failed", "snap": snap.id})

    def scroll(self, tools, a):
        snap, node, err = self._resolve(a.get("snap"), a.get("ref"))
        if err:
            return err
        dy = int(a.get("dy", 0))
        dx = int(a.get("dx", 0))
        self._focus_window(node.window)
        point = _screen_point(node)
        if point is None:
            return fail(f"{node.ref} 拿不到屏幕坐标；改用 screenshot + scroll。",
                        "not_actionable",
                        meta={"kind": "act", "effect": "failed",
                              "snap": snap.id})
        tools.mouse.move(point[0], point[1])
        tools.mouse.scroll(dy, dx)
        return ok(f"已在 {node.ref}「{node.name}」位置滚动 dy={dy} dx={dx}；"
                  "滚动事件已发出。",
                  meta={"kind": "act", "effect": "sent", "snap": snap.id})


# ---------------------------------------------------------------- 工具入口

ACTIONS = {
    "snapshot": A11y.snapshot,
    "apps": A11y.apps,
    "click": A11y.click,
    "focus": A11y.focus,
    "read": A11y.read,
    "set_text": A11y.set_text,
    "select": A11y.select,
    "scroll": A11y.scroll,
}


def ui(tools, a) -> ToolResult:
    action = str(a.get("action", "snapshot"))
    fn = ACTIONS.get(action)
    if fn is None:
        return fail(f"不支持的 ui action：{action}", "bad_args")
    try:
        return fn(tools.a11y, tools, a)
    except RuntimeError as exc:
        return fail(str(exc), "unavailable")
