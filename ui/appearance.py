"""面板外观：校验、预设、CSS 和 niri window-rule 生成。

这里不 import gi，也不碰控件；只把一份外观状态变成字符串。
真正的应用在 panel.py 里通过控件级 CssProvider 完成。
"""

from __future__ import annotations

import json
import os
import re

from core.config import atomic_write_json

FIELDS = ("opacity", "accent", "background", "radius", "font_scale",
          "blur", "xray", "noise")

PROFILE_NAME_MAX = 24

DEFAULTS = {
    "opacity": 0.80,
    "accent": "#b9a7f5",
    "background": "#111116",
    "radius": 16,
    "font_scale": 1.0,
    "blur": False,
    "xray": True,
    "noise": 0.02,
}

PRESETS = {
    "default": dict(DEFAULTS),
    "midnight": {
        "opacity": 0.80, "accent": "#8ab4ff", "background": "#0b1020",
        "radius": 18, "font_scale": 1.0,
        "blur": True, "xray": True, "noise": 0.02,
    },
    "warm": {
        "opacity": 0.82, "accent": "#f0a868", "background": "#1a1210",
        "radius": 14, "font_scale": 1.0,
        "blur": True, "xray": True, "noise": 0.02,
    },
    "cyan": {
        "opacity": 0.78, "accent": "#67e8f9", "background": "#081418",
        "radius": 16, "font_scale": 1.0,
        "blur": True, "xray": True, "noise": 0.02,
    },
    "mono": {
        "opacity": 0.85, "accent": "#d4d4d8", "background": "#0c0c0f",
        "radius": 12, "font_scale": 1.0,
        "blur": False, "xray": True, "noise": 0.02,
    },
    "rose": {
        "opacity": 0.80, "accent": "#f0a3c8", "background": "#170f16",
        "radius": 18, "font_scale": 1.0,
        "blur": True, "xray": True, "noise": 0.02,
    },
}

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# 基础字号；font_scale 会乘到这些值上。
_FONT_SIZES = {
    ".assistant-text": 10.5,
    ".user-text": 10.0,
    ".tool-title": 8.5,
    ".tool-detail": 8.0,
    ".notice-text": 9.0,
    ".error-text": 9.0,
    ".confirm-text": 9.5,
    ".empty-title": 12.0,
    ".empty-hint": 8.5,
    ".narration": 8.5,
    "entry": 10.5,
    ".setup-title": 15.0,
    ".setup-sub": 9.0,
    ".setup-feature-text": 9.0,
    ".setup-key-desc": 8.5,
    ".setup-label": 8.0,
    ".setup-status": 8.5,
    ".setup-code": 7.0,
    ".setup-mock-text": 8.5,
}


def _color(value, fallback):
    if isinstance(value, str):
        text = value.strip()
        if not text.startswith("#"):
            text = "#" + text
        if _HEX.match(text):
            text = text.lower()
            if len(text) == 4:
                text = "#" + "".join(ch * 2 for ch in text[1:])
            return text
    return fallback


def _bool(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def normalize(state) -> dict:
    """把一份可能来自模型/JSON 的外观状态夹到安全范围。"""
    src = state or {}
    out = {k: src[k] for k in FIELDS if k in src}
    try:
        opacity = float(out.get("opacity", DEFAULTS["opacity"]))
    except (TypeError, ValueError):
        opacity = DEFAULTS["opacity"]
    out["opacity"] = round(max(0.2, min(1.0, opacity)), 2)
    out["accent"] = _color(out.get("accent"), DEFAULTS["accent"])
    out["background"] = _color(out.get("background"), DEFAULTS["background"])
    try:
        radius = int(out.get("radius", DEFAULTS["radius"]))
    except (TypeError, ValueError):
        radius = DEFAULTS["radius"]
    out["radius"] = max(0, min(28, radius))
    try:
        scale = float(out.get("font_scale", DEFAULTS["font_scale"]))
    except (TypeError, ValueError):
        scale = DEFAULTS["font_scale"]
    out["font_scale"] = round(max(0.85, min(1.3, scale)), 2)
    out["blur"] = _bool(out.get("blur"), DEFAULTS["blur"])
    out["xray"] = _bool(out.get("xray"), DEFAULTS["xray"])
    try:
        noise = float(out.get("noise", DEFAULTS["noise"]))
    except (TypeError, ValueError):
        noise = DEFAULTS["noise"]
    out["noise"] = round(max(0.0, min(0.1, noise)), 3)
    return out


def clean_name(name):
    """配置名：去空白、限长、不允许换行；default 保留给默认外观。"""
    if not isinstance(name, str):
        return None
    text = name.strip()
    if not text or len(text) > PROFILE_NAME_MAX:
        return None
    if any(ch in text for ch in "\r\n\t"):
        return None
    if text.lower() == "default":
        return None
    return text


def empty_store(fallback=None):
    return {"default": normalize(fallback or DEFAULTS), "profiles": {}}


def load_store(path, fallback=None):
    """读默认外观和命名配置；坏文件按空仓库处理。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return empty_store(fallback)
    if not isinstance(raw, dict):
        return empty_store(fallback)
    default = raw.get("default")
    if not isinstance(default, dict):
        default = fallback if isinstance(fallback, dict) else DEFAULTS
    profiles = {}
    saved = raw.get("profiles")
    if isinstance(saved, dict):
        for name, state in saved.items():
            key = clean_name(name)
            if key and isinstance(state, dict):
                profiles[key] = normalize(state)
    return {"default": normalize(default), "profiles": profiles}


def save_store(path, store):
    """写回时重新校验，避免手改文件带进坏值。"""
    store = store or {}
    raw = store.get("profiles")
    profiles = {}
    if isinstance(raw, dict):
        for name, state in raw.items():
            key = clean_name(name)
            if key and isinstance(state, dict):
                profiles[key] = normalize(state)
    clean = {
        "default": normalize(store.get("default") or DEFAULTS),
        "profiles": profiles,
    }
    atomic_write_json(path, clean)
    return clean


def ensure_store(path, fallback=None):
    """首次启动时把当前外观固定成默认，之后 restore 才有东西可回。"""
    store = load_store(path, fallback)
    if not os.path.exists(path):
        try:
            save_store(path, store)
        except OSError:
            pass
    return store


def _rgb(color):
    text = color.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def _rgba(color, alpha):
    r, g, b = _rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha:g})"


def css(state) -> str:
    """生成覆盖 style.css 的控件级样式。"""
    s = normalize(state)
    accent = s["accent"]
    lines = [
        "/* generated by ui/appearance.py */",
        ".root {",
        f"  background-color: {_rgba(s['background'], s['opacity'])};",
        f"  border-radius: {s['radius']}px;",
        "}",
        f".thinking-dot, .tool-dot {{ background-color: {accent}; }}",
        (".tool-dot.tool-dot-done { animation: none; "
         "background-color: rgba(150, 220, 170, 0.55); }"),
        f".stream-caret {{ color: {_rgba(accent, 0.85)}; }}",
        f"entry {{ caret-color: {accent}; }}",
        f"button.send {{ color: {_rgba(accent, 0.80)}; }}",
        ("button.send:hover { background-color: %s; color: %s; }"
         % (_rgba(accent, 0.14), _rgba(accent, 0.95))),
        f"button.send:active {{ background-color: {_rgba(accent, 0.20)}; }}",
        f".assistant-name {{ color: {_rgba(accent, 0.40)}; }}",
        f".input-bar:focus-within {{ border-color: {_rgba(accent, 0.22)}; }}",
        f"spinner {{ color: {_rgba(accent, 0.70)}; }}",
        (" .tool-bar { background-image: linear-gradient(to right, %s, %s, %s); }"
         % (_rgba(accent, 0.0), _rgba(accent, 0.55), _rgba(accent, 0.0))),
        # style.css 里的呼吸和完成闪光把紫色写死在 keyframes 里；
        # 换一个动画名，才能跟着 accent 走。
        "@keyframes archlot-breathe {",
        "  0%, 100% { border-color: rgba(255, 255, 255, 0.06); }",
        f"  50% {{ border-color: {_rgba(accent, 0.20)}; }}",
        "}",
        (".root.state-idle { animation: archlot-breathe 5.5s "
         "ease-in-out infinite; }"),
        (".root.state-busy { animation: archlot-breathe 1.5s "
         "ease-in-out infinite; }"),
        "@keyframes archlot-cardpop {",
        f"  0% {{ background-color: {_rgba(accent, 0.16)}; }}",
        "  100% { background-color: rgba(255, 255, 255, 0.026); }",
        "}",
        ".tool-card.tool-done { animation: archlot-cardpop 0.45s ease-out 1; }",
        f"button.setup-next {{ background-color: {_rgba(accent, 0.14)}; "
        f"border-color: {_rgba(accent, 0.28)}; color: {_rgba(accent, 0.95)}; }}",
        ("button.setup-next:hover { background-color: %s; border-color: %s; }"
         % (_rgba(accent, 0.22), _rgba(accent, 0.44))),
        f"button.setup-toggle:checked {{ background-color: {_rgba(accent, 0.16)}; "
        f"border-color: {_rgba(accent, 0.36)}; }}",
        f"button.preset.active {{ border-color: {_rgba(accent, 0.46)}; "
        f"background-color: {_rgba(accent, 0.10)}; }}",
        f"scale highlight {{ background-color: {_rgba(accent, 0.58)}; }}",
        f"scale slider {{ background-color: {_rgba(accent, 0.92)}; }}",
        f".setup-dots {{ color: {_rgba(accent, 0.45)}; }}",
        f".setup-step {{ color: {_rgba(accent, 0.55)}; }}",
        f".setup-value {{ color: {_rgba(accent, 0.78)}; }}",
        f".setup-feature-key {{ color: {_rgba(accent, 0.85)}; }}",
        f".setup-field:focus-within {{ border-color: {_rgba(accent, 0.28)}; }}",
        f"entry > text > selection {{ background-color: {_rgba(accent, 0.32)}; }}",
        ("entry > text > selection:focus { background-color: %s; }"
         % _rgba(accent, 0.42)),
    ]
    for selector, base in _FONT_SIZES.items():
        size = base * s["font_scale"]
        lines.append(f"{selector} {{ font-size: {size:.2f}pt; }}")
    return "\n".join(lines) + "\n"


def niri_rule(state, app_id: str = "com.cqsomt.archlot") -> str:
    """生成 niri 26.04+ 的 window-rule。

    不在规则里写 opacity：Archlot 自己用 CSS alpha 控制透明度，
    niri 的 opacity 会叠乘。模糊和圆角裁剪由 niri 负责。
    """
    s = normalize(state)
    pattern = "^" + re.escape(app_id) + "$"
    lines = [
        "// Archlot niri window-rule（模糊需要 niri 26.04+）",
        "// 放进 ~/.config/niri/config.kdl，保存后 niri 会自动重载。",
        "window-rule {",
        f'    match app-id=r#"{pattern}"#',
        f"    geometry-corner-radius {s['radius']}",
        "    clip-to-geometry true",
    ]
    if s["blur"]:
        lines.extend([
            "    background-effect {",
            "        blur true",
            f"        xray {'true' if s['xray'] else 'false'}",
            f"        noise {s['noise']:.3f}",
            "    }",
        ])
    lines.extend([
        "    // 不要在 niri 里再设 opacity：Archlot 已经用 CSS alpha 控制，",
        "    // niri 的 opacity 会叠乘。",
        "}",
    ])
    return "\n".join(lines)
