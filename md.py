"""极简 Markdown → Pango markup，够聊天面板用，不引第三方库。

支持：
- 行内代码、粗体、斜体、链接（只保留文字）
- 标题（加粗放大）
- 无序列表
- 围栏代码块（等宽 + 淡色）
"""

import html
import re

CODE_COLOR = "#cfc6e8"
CODE_BG = "#ffffff10"
LINK_COLOR = "#b9a7f5"


def _inline(text):
    t = html.escape(text, quote=False)
    t = re.sub(
        r"`([^`]+)`",
        lambda m: ('<span font_family="monospace" foreground="' + CODE_COLOR
                   + '">' + m.group(1) + "</span>"),
        t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: ('<span foreground="' + LINK_COLOR + '">'
                   + m.group(1) + "</span>"),
        t)
    return t


def to_markup(text):
    out = []
    in_code = False
    for line in str(text).split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            esc = html.escape(line, quote=False)
            if not esc.strip():
                esc = " "
            out.append(
                '<span font_family="monospace" foreground="' + CODE_COLOR
                + '" background="' + CODE_BG + '">' + esc + "</span>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            size = "large" if len(m.group(1)) <= 2 else "medium"
            out.append('<span size="' + size + '" weight="bold">'
                       + _inline(m.group(2)) + "</span>")
            continue
        m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if m:
            out.append(m.group(1) + "•  " + _inline(m.group(2)))
            continue
        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if m:
            out.append(m.group(1) + m.group(2) + ".  " + _inline(m.group(3)))
            continue
        if stripped.startswith(">"):
            out.append('<span foreground="#a9a2b8">'
                       + _inline(stripped.lstrip("> ")) + "</span>")
            continue
        out.append(_inline(line))
    return "\n".join(out)
