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


def _blank(out):
    """保证块与块之间恰好一个空行。"""
    if out and out[-1] != "":
        out.append("")


def _render_table(rows, has_header):
    """窄面板里，多列表格竖向展开；两列表格保持横向。"""
    if not rows:
        return []
    header = rows[0] if has_header else None
    data = rows[1:] if has_header else rows
    ncol = max(len(r) for r in rows)

    if ncol <= 2:
        out = []
        sep = '<span foreground="#5b5668">  │  </span>'
        if header:
            body = sep.join(_inline(c) for c in header)
            out.append('<span size="10240" weight="bold" '
                       'background="#ffffff0d">' + body + "</span>")
            out.append('<span foreground="#5b5668">' + "─" * 24 + "</span>")
        for i, row in enumerate(data):
            row = row + [""] * (ncol - len(row))
            body = sep.join(_inline(c) for c in row)
            bg = ' background="#ffffff07"' if i % 2 else ""
            out.append(f'<span size="10240"{bg}>{body}</span>')
        return out

    out = []
    for row in data:
        lines = []
        if row:
            lines.append('<span size="10752" weight="bold" '
                         'foreground="#f0edf7">'
                         + _inline(row[0]) + "</span>")
        for j in range(1, len(row)):
            value = _inline(row[j])
            if not value.strip():
                continue
            label = header[j] if header and j < len(header) else ""
            if label:
                lines.append('<span foreground="#8d879c">'
                             + _inline(label) + "</span>：" + value)
            else:
                lines.append(value)
        if lines:
            if out:
                out.append("")
            out.append("\n".join(lines))
    return out


def to_markup(text):
    out = []
    in_code = False
    table_rows = []
    table_header = False

    def flush_table():
        nonlocal table_rows, table_header
        if not table_rows:
            return
        _blank(out)
        out.extend(_render_table(table_rows, table_header))
        _blank(out)
        table_rows = []
        table_header = False

    for line in str(text).split("\n"):
        stripped = line.strip()
        is_table = (not in_code and stripped.startswith("|")
                    and stripped.endswith("|"))
        if table_rows and not is_table:
            flush_table()

        # 空行：合并连续空行，避免长回复被拉得太散
        if not in_code and not stripped:
            if out and out[-1] != "":
                out.append("")
            continue

        if not in_code and re.fullmatch(r"([-*_])\1{2,}", stripped):
            _blank(out)
            out.append('<span foreground="#6b6678">' + "─" * 18 + "</span>")
            _blank(out)
            continue
        if is_table:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table_header = True
                continue
            table_rows.append(cells)
            continue
        if stripped.startswith("```"):
            _blank(out)
            in_code = not in_code
            if not in_code:
                _blank(out)
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
            _blank(out)
            level = len(m.group(1))
            size = 13312 if level <= 2 else (12288 if level == 3 else 11264)
            out.append('<span size="' + str(size)
                       + '" weight="bold" foreground="#f2eff8">'
                       + _inline(m.group(2)) + "</span>")
            _blank(out)
            continue
        m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if m:
            if not (out and re.match(r"^\s*(•|\d+\.)\s", out[-1])):
                _blank(out)
            out.append(m.group(1) + "•  " + _inline(m.group(2)))
            continue
        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if m:
            if not (out and re.match(r"^\s*(•|\d+\.)\s", out[-1])):
                _blank(out)
            out.append(m.group(1) + m.group(2) + ".  " + _inline(m.group(3)))
            continue
        if stripped.startswith(">"):
            _blank(out)
            out.append('<span foreground="#a9a2b8">'
                       + _inline(stripped.lstrip("> ")) + "</span>")
            continue
        out.append(_inline(line))
    flush_table()
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)
