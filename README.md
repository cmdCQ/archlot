# Archlot

住在 niri 底部的本地 AI 助手。按 **Copilot 键**（Super+Shift+F23）召唤，
输入问题或指令，Enter 发送，Esc 收起。

- 界面：GTK4，无边框浮窗，底部居中，磨砂背景（niri blur）
- 模型：DeepSeek（OpenAI 兼容接口，支持视觉 + 工具调用）
- 能力：shell、读写文件、截图看屏、鼠标点击、键盘输入、窗口切换
- 危险命令（rm / sudo / 关机等）执行前会弹确认

## 文件

| 路径 | 作用 |
| --- | --- |
| `archlot.py` | 主程序（GTK4 界面 + agent 循环） |
| `llm.py` | DeepSeek 流式客户端（仅标准库） |
| `tools.py` | 工具实现（uinput 鼠标、wtype 键盘、grim 截图、niri IPC） |
| `style.css` | 外观 |
| `bin/archlot` | 启动器 |
| `~/.config/archlot/config.json` | API key 与模型配置（600） |

## 依赖

系统自带即可：`python-gobject`、`gtk4`、`grim`、`wtype`、`wl-clipboard`、
`niri`，以及 `/dev/uinput` 写权限（用户在 `input` 组）。

## 用法

```bash
archlot            # 打开
archlot --toggle   # 切换（Copilot 键绑定的就是这个）
archlot --daemon   # 后台预热，不显示
```

快捷键：`Enter` 发送，`Esc` 收起，`Ctrl+L` 开新对话。

## 按键映射（重要）

这台机器的 Copilot 键在 xkb 里映射为：

- 单独按：`XF86TouchpadOff`
- `Super+Shift` + 该键：`XF86Assistant`（Copilot 专用 keysym）

但 niri 匹配快捷键用的是**基础层符号**，所以绑定写成：

```kdl
Mod+Shift+XF86TouchpadOff repeat=false { spawn "~/.local/bin/ai"; }
```

不要写成 `Mod+Shift+F23`（内核看是 F23，但 xkb 层不是，不会触发）。
