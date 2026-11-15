"""配置与路径的唯一来源。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, fields

APP_ID = "com.cqsomt.archlot"

CONFIG_DIR = os.path.expanduser("~/.config/archlot")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
GEOM_PATH = os.path.join(CONFIG_DIR, "window.json")
MEMORY_DIR = os.path.join(CONFIG_DIR, "memory")
HABITS_PATH = os.path.join(MEMORY_DIR, "habits.json")
LOG_PATH = "/tmp/archlot-app.log"
DEFAULT_WORKSPACE = os.path.expanduser("~/archlot-workspace")


@dataclass
class Config:
    api_base: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-flash"
    max_tokens: int = 16384
    workspace: str = DEFAULT_WORKSPACE
    sound_effects: bool = True
    confirm_mode: str = "auto"      # auto | strict
    max_steps: int = 600
    max_turn_seconds: float = 600.0
    max_tool_seconds: int = 120
    adaptive_effort: bool = False
    effort_low_after: int = 3
    effort_hold_requests: int = 2

    @classmethod
    def load(cls, path: str = CONFIG_PATH) -> "Config":
        raw = {}
        try:
            with open(path) as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            raw = {}
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in raw.items() if k in known})
        cfg.workspace = os.path.abspath(os.path.expanduser(str(cfg.workspace)))
        if not cfg.api_key:
            cfg.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if cfg.confirm_mode not in ("auto", "strict"):
            cfg.confirm_mode = "auto"
        return cfg


def atomic_write_json(path: str, data) -> None:
    """写临时文件再 rename，崩溃时不会留下半截 JSON。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
