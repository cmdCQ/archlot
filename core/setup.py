"""配置向导的纯逻辑：配置合并、niri 托管块、原子写文本。

不 import gi，不读终端；`bin/archlot-setup` 负责交互，测试直接调这里。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

MARK_BEGIN = "// >>> archlot-setup >>>"
MARK_END = "// <<< archlot-setup <<<"


def atomic_write_text(path, text, mode=0o600):
    """写临时文件再 rename；配置和 niri 文件都不能留半截。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update_config(raw, changes):
    """只覆盖调用方明确给出的字段，空值保留原配置。"""
    out = dict(raw) if isinstance(raw, dict) else {}
    for key, value in (changes or {}).items():
        if value is None:
            continue
        out[key] = value
    return out


def mask_key(key):
    text = str(key or "")
    if not text:
        return "未配置"
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}…{text[-4:]}"


def _kdl_string(value):
    text = str(value)
    if any(ch in text for ch in '"\\\n\r\t'):
        raise ValueError("路径里不能有引号、反斜杠或换行")
    return f'"{text}"'


def hotkey_block(keys, launcher):
    """生成 Copilot 键的 binds 片段。"""
    keys = str(keys or "").strip()
    if not keys or any(ch.isspace() for ch in keys):
        raise ValueError("按键组合不能为空，也不能有空格")
    return ("binds {\n"
            f"    {keys} repeat=false hotkey-overlay-title=\"AI 助手\" {{\n"
            f"        spawn {_kdl_string(launcher)};\n"
            "    }\n"
            "}")


def managed_block(app_id, window_rule, keys, launcher):
    """一整段可替换、可整段删除的 niri 配置。"""
    body = [MARK_BEGIN,
            "// 由 Archlot 配置向导维护；重跑 archlot-setup 会更新，",
            "// 想取消就把 BEGIN/END 两行之间的内容整段删掉。",
            window_rule.strip(),
            hotkey_block(keys, launcher),
            MARK_END]
    return "\n".join(body) + "\n"


def upsert_block(text, block):
    """替换已有的托管块；没有就追加到末尾。"""
    text = text or ""
    block = block.strip() + "\n"
    start = text.find(MARK_BEGIN)
    end = text.find(MARK_END)
    if start != -1 and end != -1 and end > start:
        end += len(MARK_END)
        head = text[:start].rstrip("\n")
        tail = text[end:].lstrip("\n")
        parts = [part for part in (head, block.rstrip("\n"), tail) if part]
        return "\n\n".join(parts) + "\n"
    if not text.strip():
        return block
    return text.rstrip("\n") + "\n\n" + block


def mentions_app_id(texts, app_id):
    """任何一份 niri 配置里已经有这个 app-id 时，不再自动追加。"""
    needle = str(app_id)
    return any(needle in (text or "") for text in texts)


# ---------------------------------------------------------------- 图形向导

def default_niri_dir():
    """niri 配置目录；测试里也可以直接传别的目录。"""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "niri"


def niri_status(folder, app_id):
    """只读地检查 niri 配置，供图形向导显示状态。"""
    folder = Path(folder)
    config = folder / "config.kdl"
    texts = []
    try:
        for path in sorted(folder.glob("*.kdl")):
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except OSError:
                pass
    except OSError:
        pass
    config_text = ""
    if config.exists():
        try:
            config_text = config.read_text(encoding="utf-8")
        except OSError:
            pass
    return {
        "folder": str(folder),
        "path": str(config),
        "exists": config.exists(),
        "managed": MARK_BEGIN in config_text,
        "mentions": mentions_app_id(texts, app_id),
    }


def _backup_path(config):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = config.with_name(config.name + ".bak." + stamp)
    index = 2
    while backup.exists():
        backup = config.with_name(config.name + ".bak." + stamp + f"-{index}")
        index += 1
    return backup


def install_hotkey(folder, app_id, window_rule, keys, launcher):
    """把 window-rule 和 Copilot 绑定写进 niri 配置。

    返回 status:
      written              已写入（backup 是备份文件名）
      no_config            没找到 config.kdl，调用方把 block 显示给用户
      already_configured   别的配置段已经声明了 app-id，不重复写
      invalid              按键或路径不合法
    """
    try:
        block = managed_block(app_id, window_rule, keys, launcher)
    except ValueError as exc:
        return {"status": "invalid", "error": str(exc), "block": ""}

    status = niri_status(folder, app_id)
    if not status["exists"]:
        return {"status": "no_config", "block": block, **status}
    if status["mentions"] and not status["managed"]:
        return {"status": "already_configured", "block": block, **status}

    config = Path(status["path"])
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as exc:
        return {"status": "error", "error": str(exc), "block": block, **status}
    backup = _backup_path(config)
    try:
        shutil.copy2(config, backup)
        atomic_write_text(
            str(config), upsert_block(text, block), mode=0o644)
    except OSError as exc:
        return {"status": "error", "error": str(exc), "block": block, **status}
    return {
        "status": "written",
        "backup": backup.name,
        "block": block,
        **status,
    }
