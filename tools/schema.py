"""工具的 JSON schema（给模型看）。"""

TOOLS = [
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "在工作区执行 bash 命令并返回输出。危险操作执行前会请求确认。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文本文件内容。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer", "description": "最多读取字符数，默认 20000"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "写入文件（默认工作区；严格模式下写工作区外会请求确认）。会覆盖原内容。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "列出目录内容。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "默认工作区"},
        }},
    }},
    {"type": "function", "function": {
        "name": "screenshot",
        "description": "截取整个屏幕给自己看，返回 frame 编号。之后 click/move_mouse 用这张图的像素坐标，并带上 frame。",
        "parameters": {"type": "object", "properties": {
            "scale": {"type": "number", "description": "缩放，默认 0.8；看整页布局可用 0.6，越大小目标越准"},
        }},
    }},
    {"type": "function", "function": {
        "name": "click",
        "description": "用鼠标点击屏幕。坐标是截图图片像素，必须带 frame。只保证事件发出，不保证点中目标；关键操作后截图确认。",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "frame": {"type": "integer", "description": "screenshot 返回的 frame；省略用最新一张，过期会被拒绝"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "double": {"type": "boolean"},
        }, "required": ["x", "y"]},
    }},
    {"type": "function", "function": {
        "name": "move_mouse",
        "description": "移动鼠标（截图像素坐标），不点击。",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "frame": {"type": "integer", "description": "screenshot 返回的 frame"},
        }, "required": ["x", "y"]},
    }},
    {"type": "function", "function": {
        "name": "scroll",
        "description": "滚动鼠标滚轮。dy 正数向下，负数向上。",
        "parameters": {"type": "object", "properties": {
            "dy": {"type": "integer"}, "dx": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "向当前焦点窗口输入文字。method=auto 默认（英文用 wtype，中文走剪贴板）；method=keys 用真实键码（noVNC/KVM 网页控制台、游戏等收不到文字时用）；method=paste 强制剪贴板粘贴。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "method": {"type": "string", "enum": ["auto", "keys", "paste"]},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "memory",
        "description": "长期记忆。add 记一条稳定事实（用户偏好/环境/长期项目/明确要求）；search 检索；forget 按 id 或关键词删除；list 列出最近的。不要记一次性任务细节。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["add", "search", "forget", "list"]},
            "text": {"type": "string", "description": "add 时要记的内容"},
            "tags": {"type": "string"},
            "query": {"type": "string"},
            "id": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": ["action"]},
    }},
    {"type": "function", "function": {
        "name": "panel",
        "description": "控制 Archlot 自己的窗口（用户让它改布局时用）。action=info 查看；move 移动；resize 缩放；set 同时设位置和尺寸；dock 贴边停靠；opacity 设透明度；hide/show 收起或唤出；reset 恢复默认。尺寸单位是逻辑像素，屏幕 2048x1280 时默认 380x880。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["info", "move", "resize", "set", "dock",
                                "opacity", "hide", "show", "reset"]},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "edge": {"type": "string", "enum": ["left", "right", "top", "bottom"]},
            "margin": {"type": "integer"},
            "size": {"type": "integer"},
            "opacity": {"type": "number"},
        }, "required": ["action"]},
    }},
    {"type": "function", "function": {
        "name": "press_key",
        "description": "按组合键，例如 ctrl+l、alt+Tab、Return、Escape。method=keys 用真实键码（noVNC/KVM 控制台等收不到按键时用）。",
        "parameters": {"type": "object", "properties": {
            "keys": {"type": "string"},
            "method": {"type": "string", "enum": ["auto", "keys"]},
        }, "required": ["keys"]},
    }},
    {"type": "function", "function": {
        "name": "list_windows",
        "description": "列出当前所有窗口（id、app_id、标题、是否焦点）。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "focus_window",
        "description": "切换焦点到某个窗口，可按 id / app_id / 标题片段。",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"},
            "app_id": {"type": "string"},
            "title": {"type": "string"},
        }},
    }},
]
