# Archlot

住在 niri 桌面上的本地 AI 助手。按 **Copilot 键**（Super+Shift+F23）召唤，
输入问题或指令，Enter 发送，Esc 收起。

- 界面：GTK4，无边框浮窗，右侧竖栏，磨砂背景（niri blur）
- 模型：DeepSeek（OpenAI 兼容接口，支持视觉 + 工具调用）
- 能力：shell、读写文件、截图看屏、鼠标点击、键盘输入、窗口切换
- 危险命令（rm / sudo / 关机等）执行前会弹确认

## 文件

| 路径 | 作用 |
| --- | --- |
| `archlot.py` | 入口 + 模块接线 |
| `core/` | 配置、契约、系统机制、LLM、记忆 |
| `agent/` | 对话循环、消息历史、提示词 |
| `tools/` | 工具、策略、输入设备、schema |
| `ui/` | GTK 面板、消息渲染、声效 |
| `style.css` | 外观 |
| `bin/archlot` | 启动器 |
| `~/.config/archlot/config.json` | API key 与模型配置（600） |

改代码前先读 `AGENT.md`。

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

---

## 交接

新接手请先读：

- `AGENT.md` — 改代码的硬规矩（唯一规范源）
- `CLAUDE.md` — 架构速览、常用命令、UI 约束
- `docs/HANDOFF.md` — 踩坑记录、用户偏好

当前状态：功能可用，已按 `core / agent / tools / ui` 分层；
策略统一在 `tools/policy.py`，消息历史统一在 `agent/history.py`。
