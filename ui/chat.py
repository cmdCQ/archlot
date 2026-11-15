"""消息展示用的工具文案。"""

from __future__ import annotations

import json

TOOL_LABELS = {
    "run_shell": "终端", "screenshot": "截屏", "click": "点击",
    "type_text": "输入", "press_key": "按键", "move_mouse": "移动鼠标",
    "scroll": "滚动", "list_windows": "窗口列表", "focus_window": "切换窗口",
    "read_file": "读取文件", "write_file": "写入文件", "list_dir": "目录",
    "panel": "调整窗口", "appearance": "外观", "memory": "记忆",
}


def tool_preview(name, args):
    try:
        if name == "run_shell":
            return str(args.get("command", "")).replace("\n", " ⏎ ")
        if name == "click":
            return f"({args.get('x')}, {args.get('y')})"
        if name == "type_text":
            return str(args.get("text", ""))
        if name == "press_key":
            return str(args.get("keys", ""))
        if name in ("read_file", "write_file", "list_dir"):
            return str(args.get("path", ""))
        if name == "panel":
            return str(args.get("action", ""))
        if name == "appearance":
            action = str(args.get("action", ""))
            extra = args.get("name") or args.get("preset")
            return f"{action} {extra}" if extra else action
        if name == "focus_window":
            return f"窗口 {args.get('id')}"
        if name == "memory":
            return str(args.get("action", ""))
        return json.dumps(args, ensure_ascii=False)[:80]
    except Exception:  # noqa: BLE001
        return ""
