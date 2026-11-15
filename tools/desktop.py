"""桌面工具：截图、鼠标、键盘、窗口、面板。"""

from __future__ import annotations

import os
import time

from core import system
from core.contracts import ToolResult, fail, ok
from .devices import (paste_text, press_combo_uinput, press_wtype,
                      type_with_uinput)


def to_screen(x, y, image_size_value, screen_size_value):
    """截图像素 → 逻辑坐标。不要 int 截断。"""
    if image_size_value:
        iw, ih = image_size_value
        if iw and ih:
            sw, sh = screen_size_value
            return float(x) * sw / iw, float(y) * sh / ih
    return float(x), float(y)


def screenshot(tools, a) -> ToolResult:
    scale = float(a.get("scale", 0.8))
    path = system.new_shot_path()
    if tools.ctx.before_shot:
        tools.ctx.before_shot()
    try:
        rc, _, err = system.run(
            ["grim", "-s", str(scale), "-t", "jpeg", "-q", "80",
             path], timeout=15)
    finally:
        if tools.ctx.after_shot:
            tools.ctx.after_shot()
    if rc != 0:
        try:
            os.unlink(path)
        except OSError:
            pass
        return fail(f"截图失败：{err.strip()}", "screenshot")
    size = system.image_size(path)
    if not size or not size[0] or not size[1]:
        try:
            os.unlink(path)
        except OSError:
            pass
        return fail("截图尺寸读取失败", "screenshot")
    sw, sh = system.screen_size()
    shot = tools.add_shot(path, size, (sw, sh), scale)
    return ok(
        f"截图完成：frame={shot.id}，图片 {size[0]}x{size[1]}，"
        f"逻辑屏幕 {sw}x{sh}。后续 click/move_mouse 用这张图的像素坐标，"
        f"并带上 frame={shot.id}。",
        image=path,
        meta={"kind": "observe", "frame": shot.id,
              "size": list(size), "scale": scale})


def _click_target(tools, a):
    shot = tools.get_shot(a.get("frame"))
    if shot is not None:
        return shot, None
    if tools.last_frame is None:
        return None, fail("还没有截图；先 screenshot 再按图像坐标点击。",
                          "bad_args")
    return None, fail("frame 不存在或已过期；重新 screenshot 后再点。",
                      "stale_frame")


def click(tools, a) -> ToolResult:
    shot, err = _click_target(tools, a)
    if err:
        return err
    x, y = to_screen(float(a.get("x", 0)), float(a.get("y", 0)),
                     shot.image_size, shot.screen_size)
    panel = tools.ctx.panel
    parked = bool(panel and panel.park_panel(x, y))
    try:
        tools.mouse.click(x, y, str(a.get("button", "left")),
                          bool(a.get("double", False)))
    finally:
        if parked and panel:
            panel.unpark_panel()
    return ok(f"已发送点击 ({int(x)}, {int(y)})，frame={shot.id}；"
              "只保证事件发出，不保证目标响应。",
              meta={"kind": "act", "effect": "sent", "frame": shot.id})


def move_mouse(tools, a) -> ToolResult:
    shot, err = _click_target(tools, a)
    if err:
        return err
    x, y = to_screen(float(a.get("x", 0)), float(a.get("y", 0)),
                     shot.image_size, shot.screen_size)
    tools.mouse.move(x, y)
    return ok(f"鼠标移到 ({int(x)}, {int(y)})，frame={shot.id}",
              meta={"kind": "act", "effect": "sent", "frame": shot.id})


def scroll(tools, a) -> ToolResult:
    dy = int(a.get("dy", 0))
    dx = int(a.get("dx", 0))
    tools.mouse.scroll(dy, dx)
    return ok(f"已滚动 dy={dy} dx={dx}",
              meta={"kind": "act", "effect": "sent"})


def type_text(tools, a) -> ToolResult:
    text = str(a.get("text", ""))
    if not text:
        return fail("文本为空", "bad_args")
    method = str(a.get("method", "auto"))
    if method == "keys":
        okk, missing = type_with_uinput(text)
        if not okk:
            return fail(f"真实键码输入失败：{missing[0]}", "input")
        note = (f"（{len(missing)} 个字符不支持：{''.join(missing[:8])}）"
                if missing else "")
        return ok(f"已用真实键码输入 {len(text) - len(missing)} 个字符{note}",
                  meta={"kind": "act", "effect": "sent"})
    if method == "paste":
        okk, err = paste_text(text)
        return (ok(f"已通过剪贴板粘贴 {len(text)} 个字符",
                   meta={"kind": "act", "effect": "sent"}) if okk
                else fail(err, "input"))
    if text.isascii():
        rc, _, err = system.run(["wtype", "--", text], timeout=30)
        if rc != 0:
            return fail(f"打字失败：{err.strip()}", "input")
        return ok(f"已输入 {len(text)} 个字符",
                  meta={"kind": "act", "effect": "sent"})
    okk, err = paste_text(text)
    return (ok(f"已输入 {len(text)} 个字符",
               meta={"kind": "act", "effect": "sent"}) if okk
            else fail(err, "input"))


def press_key(tools, a) -> ToolResult:
    keys = str(a.get("keys", "")).strip()
    if not keys:
        return fail("按键为空", "bad_args")
    if str(a.get("method", "auto")) == "keys":
        okk, err = press_combo_uinput(keys)
        return (ok(f"已用真实键码按下 {keys}",
                   meta={"kind": "act", "effect": "sent"}) if okk
                else fail(err, "input"))
    okk, err = press_wtype(keys)
    return (ok(f"已按键 {keys}",
               meta={"kind": "act", "effect": "sent"}) if okk
            else fail(f"按键失败：{err}", "input"))


def list_windows(tools, a) -> ToolResult:
    lines = []
    for w in system.list_windows():
        marks = " *焦点*" if w.get("is_focused") else ""
        title = (w.get("title") or "")[:60]
        lines.append(f"{w.get('id')}  {w.get('app_id')}  {title}{marks}")
    return ok("\n".join(lines) or "没有窗口", meta={"kind": "observe"})


def focus_window(tools, a) -> ToolResult:
    wins = system.list_windows()
    target = None
    if a.get("id") is not None:
        target = next((w for w in wins
                       if str(w.get("id")) == str(a["id"])), None)
    elif a.get("app_id"):
        needle = str(a["app_id"]).lower()
        target = next((w for w in wins
                       if needle in (w.get("app_id") or "").lower()), None)
    elif a.get("title"):
        needle = str(a["title"]).lower()
        target = next((w for w in wins
                       if needle in (w.get("title") or "").lower()), None)
    if not target:
        return fail("没找到这个窗口", "not_found")
    system.run(["niri", "msg", "action", "focus-window",
                "--id", str(target["id"])], timeout=5)
    time.sleep(0.05)
    now = next((w for w in system.list_windows()
                if str(w.get("id")) == str(target["id"])), None)
    effect = "confirmed" if now and now.get("is_focused") else "sent"
    return ok(f"已聚焦 {target.get('app_id')}：{target.get('title')}",
              meta={"kind": "act", "effect": effect})


def panel(tools, a) -> ToolResult:
    ui = tools.ctx.panel
    if ui is None:
        return fail("窗口控制不可用。", "unavailable")
    action = str(a.get("action", "info"))
    cur = ui.panel_info()

    def num(key, fallback):
        v = a.get(key)
        return fallback if v is None else int(v)

    if action == "info":
        info = cur
    elif action == "move":
        info = ui.panel_move(num("x", cur["x"]), num("y", cur["y"]))
    elif action == "resize":
        info = ui.panel_resize(num("width", cur["width"]),
                               num("height", cur["height"]))
    elif action == "set":
        info = ui.panel_set(num("x", cur["x"]), num("y", cur["y"]),
                            num("width", cur["width"]),
                            num("height", cur["height"]))
    elif action == "dock":
        edge = str(a.get("edge", "right"))
        size = a.get("size")
        info = ui.panel_dock(edge, num("margin", 18),
                             int(size) if size is not None else None)
    elif action == "opacity":
        info = ui.panel_opacity(a.get("opacity", 1.0))
    elif action == "hide":
        ui.request_hide()
        time.sleep(0.25)
        cur["visible"] = False
        info = cur
    elif action == "show":
        ui.request_show()
        time.sleep(0.25)
        info = ui.panel_info()
    elif action == "reset":
        info = ui.panel_reset()
    else:
        return fail(f"不支持的 action：{action}", "bad_args")
    if action in ("move", "resize", "set", "dock", "reset", "opacity"):
        # 等 niri 的窗口动画走完，读回的位置才是最终值
        time.sleep(0.28)
        info = ui.panel_info()
    return ok(f"窗口 x={info['x']} y={info['y']} "
              f"{info['width']}x{info['height']} "
              f"屏幕 {info['screen_width']}x{info['screen_height']} "
              f"可见={info['visible']} 透明度={info['opacity']} "
              f"内容最小={info.get('min_width')}x{info.get('min_height')}",
              meta={"kind": "act" if action != "info" else "observe",
                    "effect": "confirmed"})
