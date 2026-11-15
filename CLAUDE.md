# Archlot

住在 niri 桌面上的本地 AI 助手。GTK4 + Python，DeepSeek（OpenAI 兼容）后端。

## 快速开始

```bash
bin/archlot --toggle      # 唤出 / 收起
bin/archlot               # 显示
bin/archlot --setup       # 首次打开教程向导；之后打开设置（模型 / 外观 / 快捷键）
bin/archlot --daemon      # 只驻留，不显示

~/.config/archlot/config.json       # 模型配置
~/.config/archlot/window.json       # 位置 / 尺寸 / 当前外观
~/.config/archlot/appearance.json   # 默认外观 + 命名配置
/tmp/archlot-app.log                # llm / 工具耗时、策略、记忆写入

./install.sh            # 用户级安装（~/.local），--no-setup 跳过向导
./uninstall.sh          # 干净卸载，--purge 连配置和记忆
bin/archlot-setup       # 终端备用向导（无图形会话时）
```

## 架构

```
archlot.py        入口 + 接线
bin/              archlot 启动器 / archlot-setup 配置向导
install.sh        用户级安装；uninstall.sh 干净卸载
core/             config / contracts / system / llm / memory / setup
agent/            loop / effort / history / prompts
tools/            policy / files / desktop / a11y / recall / devices / schema
ui/               panel / onboarding / chat / markdown / sound
```

依赖单向：`archlot.py → agent / tools / ui → core`。
`core/` 不认识上层；`agent/`、`tools/`、`ui/` 互不 import。

**改代码前必读 `AGENT.md`**：线程边界、策略、消息历史、工具结果、验证方式都在那里。

## 关键约束（摘要）

1. **GTK 只在 `ui/` 里碰。** 跨线程走 `UI` 端口，`Panel` 自己切主线程。
   主线程不跑 niri / grim / shell 子进程。
2. **窗口尺寸非 resizable。** `root.set_size_request(w, h)`；缩小前先把最小尺寸压到目标以下。
3. **透明度作用在 `.root` 的 CSS alpha**（控件级 CssProvider），不用 `win.set_opacity`。
   `win.set_opacity` 只用于收起淡出。
4. **截图坐标到屏幕坐标**必须浮点换算，不要 `int()` 截断。
   截图默认 0.8 倍、叠加 100px 网格和 200px 标签；小目标建议 1.0。
   表单优先点第一个字段后用 Tab 串行，不要逐格猜坐标。
5. **Pango span alpha** 用 1–65535；`0`、`0%`、`65536` 都会让整段
   `set_markup` 解析失败，流式文字会卡住。不可见用 `alpha="1"`。
6. **niri 会夹取浮动窗口**，隐藏用“淡出 + unmap”，不要依赖位移。
7. **`wl-copy` 会 fork**，必须丢 stdout/stderr，否则管道不关会卡到超时。
8. **noVNC / KVM 不认 wtype 虚拟键盘**，用 `method="keys"` 走 uinput 真实键码。
9. **AT-SPI 只允许在 `tools/a11y.py` 里 import**，只在 worker 线程用，
   不创建 GTK 控件。有可访问性树时 `ui` 优先；没树就明确退回截图。

## 工具（16 个）

`run_shell` `read_file` `write_file` `list_dir` `screenshot` `ui` `click`
`move_mouse` `scroll` `type_text` `press_key` `list_windows` `focus_window`
`panel` `appearance` `memory`

- 默认工作区 `~/archlot-workspace`，也是 shell 的 cwd
- 工作区外写入默认放行但会在结果里标注；`confirm_mode=strict` 时才询问
- 危险命令（sudo、mkfs、dd、关机、卸载包、删系统目录）一律弹确认

## 记忆

- `~/.config/archlot/memory/profile.md` 用户档案（每轮注入）
- `facts.db` 事实库（FTS5，tags 含 偏好/环境/项目/经验），启动时本地聚类去重
- `notes/YYYY-MM.md` 会话小结
- 失败反思会自动写“经验”，但排除内容政策类结论

## 视觉

- 右侧竖栏，默认 380×880，贴右居中，可拖标题栏移动
- 首次启动自动打开一次性的面板内向导（`ui/onboarding.py`）：
  教程 → 模型 → 外观实时预览 → Copilot 键 → 完成；完成状态存
  `config.json` 的 `onboarding_done`。完成后再点标题栏 ⚙ 或 `--setup`
  打开的是设置面板（模型 / 外观 / 快捷键页签），不再播放教程
- 默认背景 alpha 0.8，`panel(opacity=...)` 或 `appearance(opacity=...)` 可调
- 外观状态存在 `window.json` 的 `opacity accent background radius font_scale
  blur xray noise` 字段；默认外观和命名配置存在 `appearance.json`
  （`{"default": {...}, "profiles": {...}}`）
- 校验、预设、存储、CSS、niri 规则都在 `ui/appearance.py`（不 import gi）
- `appearance(action="niri")` 生成 window-rule：niri 负责模糊和圆角裁剪，
  **不要在 niri 规则里写 opacity**，会与 CSS alpha 叠乘
- 状态呼吸：待机 5.5s、干活 1.5s、出错闪红
- 流式光标、消息上滑入场、清空淡出、平滑滚动
- 声效可关：`"sound_effects": false`

## 验证

```bash
python -m compileall -q core agent tools ui archlot.py
python -m unittest discover -s tests -t .
```

详细交接见 `docs/HANDOFF.md`。
