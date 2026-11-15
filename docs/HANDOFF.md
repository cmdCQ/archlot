# 交接文档

写给接手的人（或 Claude Code）。这里记录**代码里看不出来的上下文**：踩过的坑、用户的偏好、还没做完的决定。

仓库：`~/projects/archlot`，主分支 `main`。
运行：`bin/archlot --toggle`。日志：`/tmp/archlot-app.log`。
安装：`./install.sh`；图形向导：`bin/archlot --setup`；卸载：`./uninstall.sh`。

---

## 1. 这个项目是什么

用户（cqsomt，Arch Linux + niri）的私人桌面助手：
- 唤出方式：Copilot 键（niri 里绑 `Mod+Shift+XF86TouchpadOff` → `~/.local/bin/ai`）
- 形态：右侧竖栏，可拖动、可改尺寸、可调透明度
- 能力：shell、文件、截图、鼠标键盘、窗口切换、长期记忆
- 后端：DeepSeek `deepseek-flash`（OpenAI 兼容），流式

用户的真实用法是**让它操作电脑**：填网页表单、点按钮、开浏览器、跑命令、改配置。不是聊天机器人。

---

## 2. 用户偏好（很重要，别踩雷）

- **讨厌反复确认**。普通命令直接执行；只有真正危险的才弹框。
- **喜欢直接动手**，不要一遍遍解释方案。大改之前可以先给一次方案，但别反复问。
- **讨厌“假装有意识”**。要的是存在感（状态、连续性、分寸），不是拟人化文案。
- **UI 要求高**：嫌过“廉价”“太重”“不够灵动”。当前方向：轻、平、少装饰、紫色只做点缀。
- **透明度**：默认 0.8；嫌 0.95 太实、0.76 太透。可以让他自己用 `panel` 或
  `appearance` 工具调。调完的外观可以存成默认，`appearance(action="restore")` 一键恢复。
- **要 Markdown 渲染**，且不要用“你偏好不用 Markdown”这种过时记忆来反驳他。
- **不要擅自改思考强度**：之前偷偷改 `reasoning_effort` 被骂过。要加就做成显式策略并可见。
- 记忆里不要留存“内容政策/拒绝类”经验，会自我强化。

---

## 3. 当前实现要点

### 3.1 窗口与位置
- `ui/panel.py` 里 `IDLE/TAB` 已废弃；现在是单一面板 `PANEL_W=380`
- 位置/尺寸/透明度持久化在 `~/.config/archlot/window.json`
- `_clamp_geom()` 保证窗口在屏幕内；`_fit_to_screen()` 每 3 秒检查分辨率/缩放变化并重新贴边
- 拖动：标题栏 `Gtk.GestureClick` → `surface.begin_move()`
- 隐藏：`hide()` 淡出 12 帧后 `unmap`；不常驻小方块

### 3.2 尺寸
- 窗口 `set_resizable(False)`，`root.set_size_request(w,h)` 生效
- 缩小必须“两步”：先设 `w-1,h-1`，20ms 后再设目标值（`_apply_panel`）
- 内容最小尺寸约 172×110；`_apply_chrome()` 会在小尺寸时隐藏标题行和空状态

### 3.3 透明度
- 控件级 `Gtk.CssProvider` 挂在 `root` 上，覆盖 `.root { background-color: rgba(17,17,22,a) }`
- `panel(action="opacity", opacity=1.0)` 设的是这个 alpha；1.0 完全不透明
- `win.set_opacity` 只用于淡出动画，不要混用

### 3.4 图形配置向导
- `ui/onboarding.py`，作为 `Gtk.Stack` 的 setup 页嵌在同一个面板里，不另开窗口。
- 首次启动（`config.json` 没有 `onboarding_done`）或 `--setup` 打开；标题栏 ⚙ 随时重开。
- 教程 → 模型 → 外观（预设/滑杆实时预览，保存默认/命名配置）→ Copilot 键 → 完成。
- 模型写 `config.json`（600）并更新运行中的 `Config`；快捷键复用 `core/setup.py`，
  写入前备份 `config.kdl`，已有 app-id 时只显示片段。
- 终端 `bin/archlot-setup` 保留作无图形会话备用。

### 3.5 点击精度（做过严格测试）
- 截图默认 `scale=0.8`，小目标建议 1.0
- `tools/desktop.py:to_screen()`：`x * 逻辑宽 / 图片宽`，**不要 int 截断**
- 实测：24 个 24px 目标 × 3 档缩放，72/72 命中，平均误差 0.27px，最大 0.4px
- 剩余误差来自模型“看”截图的精度：±1 图像像素在 0.45/0.6/0.8 下分别放大成 2.2/1.7/1.3 逻辑像素
- 面板挡住点击目标时 `park_panel()` 会临时挪开

### 3.6 输入
- ASCII 用 `wtype`；中文走剪贴板（`wl-copy` + `ctrl+v`，注意 fork 问题）
- `type_text(method="keys")` / `press_key(method="keys")`：uinput 真实键码，专治 noVNC/KVM 控制台
- uinput 设备创建后要等 ~450ms 再发键，否则第一个键会被吞

### 3.7 滚动
- 贴底状态 `_stick_bottom`：用户上翻自动解除，回到底部恢复
- `_scroll_tick` 每帧重读最新高度；`finish()` 后 0/120/300ms 各补一次

### 3.8 Markdown
- `ui/markdown.py` → Pango markup
- 支持标题、粗体、斜体、行内代码、代码块、列表、引用、分隔线、简单表格
- 流式输出时实时渲染；光标通过尾部字符的 alpha 闪烁
- **坑**：`alpha="0%"` 非法，必须用数值（0–65536）

### 3.9 记忆
- `core/memory.py`：SQLite + FTS5（trigram），中文用 3 字滑窗检索
- 写入：每轮自动抽取（偏好/环境/项目）+ 失败反思（经验）
- 去重：写入时相似度合并（bigram Jaccard ≥0.72），启动 / 清空会话时本地聚类（≥0.45）
- 经验类检索加权靠前；上下文里标 `[经验]`
- 清除单条：`memory(action="forget", query="关键词")`

### 3.10 动效
- 状态呼吸（CSS keyframes，按 class 切换）
- 消息 Revealer 上滑、清空淡出、工具卡扫光 + 完成高亮
- 推理旁白：取 `reasoning_content` 最后一句，260ms 节流
- 声效：`/tmp/archlot-sounds/*.wav`，`pw-play` 播放，`sound_effects` 可关

---

## 4. 重构状态

已完成（`refactor/architecture` 分支）：
- 拆成 `core / agent / tools / ui`，入口 `archlot.py` 只做接线
- 策略统一在 `tools/policy.py`，`Policy.describe()` 生成提示词里的策略段
- 消息历史统一在 `agent/history.py`，工具结果统一为 `ToolResult`
- 主线程不再跑 niri 子进程；跨线程更新走 `ui/panel.py` 的 `_ui` / `_main_sync`
- 加入 stdlib `unittest` 测试

还没做：
- 思考强度自适应。先确认 DeepSeek 是否接受 `reasoning_effort` 及可用值；
  不支持就不要硬做。若做，只在阶段边界切档，默认关，先 A/B。
- 点击精度回归脚本（6×4 的 24px 按钮网格）。

---

## 5. 测试
- `tests/test_policy.py`：危险命令分类、strict/auto 行为
- `tests/test_history.py`：tool_call 配对、裁剪、截图消息
- `tests/test_memory.py`：相似度合并、检索、忘掉
- `tests/test_markdown.py`：各类 Markdown → markup
- `tests/test_coords.py`：截图坐标 → 屏幕坐标
- `tests/test_tools.py`：schema 与 HANDLERS 一一对应

```bash
python -m unittest discover -s tests -t .
```

---

## 6. 不变量（完整版见 `AGENT.md`）
1. worker 线程不碰 GTK
2. 截图坐标精确换算，不截断
3. Pango alpha 用数值
4. 隐藏窗口不依赖移出屏幕
5. 记忆不存内容政策类“经验”
6. 危险命令必须确认；回车=允许，Esc=拒绝
7. 清空对话不销毁欢迎页组件
8. 输出预算给足（16384），否则推理会把正文吃光
