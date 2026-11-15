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
        "description": "截取整个屏幕给自己看，返回 frame 编号。默认叠加 100px 网格和 200px 坐标标签，读坐标时以网格为准。之后 click/move_mouse 用这张图的像素坐标，并带上 frame。",
        "parameters": {"type": "object", "properties": {
            "scale": {"type": "number", "description": "缩放，默认 0.8；看整页布局可用 0.6，越大小目标越准"},
            "grid": {"type": "boolean", "description": "是否叠加坐标网格，默认 true；看不清内容时设 false"},
        }},
    }},
    {"type": "function", "function": {
        "name": "ui",
        "description": "通用桌面可访问层：对暴露 AT-SPI 的原生应用/浏览器按语义操作，比坐标点击稳。snapshot 返回 snap 编号和 eN 引用（ref），之后 click/set_text/select/read/focus/scroll 带 ref。没有可访问性树时会明确提示，改用 screenshot。apps 可查看当前哪些应用暴露了树。ref 只在这次 snapshot 有效。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["snapshot", "apps", "click", "focus", "read",
                                "set_text", "select", "scroll"]},
            "window": {"type": "string",
                       "description": "snapshot 的目标窗口：id / app_id / 标题片段；默认焦点窗口"},
            "snap": {"type": "integer",
                     "description": "snapshot 返回的 snap；省略用最新一次"},
            "ref": {"type": "string",
                    "description": "snapshot 里的元素引用，例如 e5"},
            "text": {"type": "string", "description": "set_text 要写入的文本"},
            "option": {"type": "string", "description": "select 要选的选项文字"},
            "dy": {"type": "integer", "description": "scroll 纵向格数，正数向下"},
            "dx": {"type": "integer", "description": "scroll 横向格数"},
        }, "required": ["action"]},
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
        "name": "appearance",
        "description": "调整 Archlot 自己的外观（不是别的窗口）。action=info 查看（含默认外观和已保存配置）；set 改单个字段：opacity 0.2-1.0、accent/background 十六进制色、radius 0-28、font_scale 0.85-1.3；blur/xray/noise 只写进 niri 规则，由 niri 实际渲染（需要 niri 26.04+）；preset 套用预设 default/midnight/warm/cyan/mono/rose；save 不带 name 把当前存成默认、带 name 存成命名配置；load 套用命名配置；restore 一键恢复默认；delete 删除命名配置；niri 生成配套的 niri window-rule；reset 恢复出厂值（不影响已保存的默认）。",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["info", "set", "preset", "save", "load",
                                "restore", "delete", "niri", "reset"]},
            "name": {"type": "string",
                     "description": "命名配置名，最多 24 字；save 省略时保存为默认外观"},
            "opacity": {"type": "number"},
            "accent": {"type": "string", "description": "如 #b9a7f5"},
            "background": {"type": "string", "description": "如 #111116"},
            "radius": {"type": "integer"},
            "font_scale": {"type": "number"},
            "blur": {"type": "boolean"},
            "xray": {"type": "boolean"},
            "noise": {"type": "number"},
            "preset": {"type": "string",
                       "enum": ["default", "midnight", "warm", "cyan",
                                "mono", "rose"]},
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
