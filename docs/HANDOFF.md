# 交接文档

写给接手的人（或 Claude Code）。这里记录**代码里看不出来的上下文**：踩过的坑、用户的偏好、还没做完的决定。

仓库：`~/projects/archlot`，Git 干净，最新提交 `e2a9e6f`。
运行：`bin/archlot --toggle`。日志：`/tmp/archlot-app.log`。

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
- **透明度**：默认 0.8；嫌 0.95 太实、0.76 太透。可以让他自己用 `panel` 工具调。
- **要 Markdown 渲染**，且不要用“你偏好不用 Markdown”这种过时记忆来反驳他。
- **不要擅自改思考强度**：之前偷偷改 `reasoning_effort` 被骂过。要加就做成显式策略并可见。
- 记忆里不要留存“内容政策/拒绝类”经验，会自我强化。

---

## 3. 当前实现要点

### 3.1 窗口与位置
- `archlot.py` 里 `IDLE/TAB` 已废弃；现在是单一面板 `PANEL_W=380`
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

### 3.4 点击精度（做过严格测试）
- 截图默认 `scale=0.8`，小目标建议 1.0
- `Tools._to_screen()`：`x * 逻辑宽 / 图片宽`，**不要 int 截断**
- 实测：24 个 24px 目标 × 3 档缩放，72/72 命中，平均误差 0.27px，最大 0.4px
- 剩余误差来自模型“看”截图的精度：±1 图像像素在 0.45/0.6/0.8 下分别放大成 2.2/1.7/1.3 逻辑像素
- 面板挡住点击目标时 `park_panel()` 会临时挪开

### 3.5 输入
- ASCII 用 `wtype`；中文走剪贴板（`wl-copy` + `ctrl+v`，注意 fork 问题）
- `type_text(method="keys")` / `press_key(method="keys")`：uinput 真实键码，专治 noVNC/KVM 控制台
- uinput 设备创建后要等 ~450ms 再发键，否则第一个键会被吞

### 3.6 滚动
- 贴底状态 `_stick_bottom`：用户上翻自动解除，回到底部恢复
- `_scroll_tick` 每帧重读最新高度；`finish()` 后 0/120/300ms 各补一次

### 3.7 Markdown
- `md.py` → Pango markup
- 支持标题、粗体、斜体、行内代码、代码块、列表、引用、分隔线、简单表格
- 流式输出时实时渲染；光标通过尾部字符的 alpha 闪烁
- **坑**：`alpha="0%"` 非法，必须用数值（0–65536）

### 3.8 记忆
- `memory.py`：SQLite + FTS5（trigram），中文用 3 字滑窗检索
- 写入：每轮自动抽取（偏好/环境/项目）+ 失败反思（经验）
- 去重：写入时相似度合并（bigram Jaccard ≥0.72），启动 / 清空会话时本地聚类（≥0.45）
- 经验类检索加权靠前；上下文里标 `[经验]`
- 清除单条：`memory(action="forget", query="关键词")`

### 3.9 动效
- 状态呼吸（CSS keyframes，按 class 切换）
- 消息 Revealer 上滑、清空淡出、工具卡扫光 + 完成高亮
- 推理旁白：取 `reasoning_content` 最后一句，260ms 节流
- 声效：`/tmp/archlot-sounds/*.wav`，`pw-play` 播放，`sound_effects` 可关

---

## 4. 待做的重构（建议顺序）

### Phase 1 — 合并策略层（行为不变）
新建 `policy.py`：

```python
class Policy:
    def review(self, tool, args) -> Decision      # allow / ask / deny + reason
    def effort(self, phase, streak, failed) -> str | None  # low/medium/high/None
```

- 把 `tools.py` 里的 `DANGER_RE`、`DANGER_AUTO_RE`、`_is_dangerous`、`_outside_write` 搬进去
- 把 `confirm_mode` 迁到 `policy.confirm`（auto / strict），旧字段自动迁移
- `tools.py` 只调 `self.ui.policy.review(...)`；agent 循环每轮调 `policy.effort(...)`
- 所有决定写一行审计日志：`policy review=ask reason=rm_home effort=high phase=exec`

### Phase 2 — 拆文件
```
archlot.py       入口 + CLI（~120 行）
ui/panel.py      窗口、布局、动效、消息渲染
agent.py         run_agent 循环、流式、工具调度、记忆触发
config.py        默认值、迁移、读写
```
纯搬迁，不改行为。搬完用截图对比确认。

### Phase 3 — 思考强度自适应
- 阶段：`planning`（新用户消息）/ `executing`（连续简单工具）/ `verifying`（截图确认、读结果）
- `executing` 连续 ≥3 轮无失败 → `low`；`verifying` → `medium`
- 任何失败 → `high`，保持 2 轮
- **只在阶段边界切换**，不要每步都改（会抖）
- 默认 `off`，先 A/B 测量再决定是否默认开

参考实现（GitHub）：
- `robertn702/reasoning-router` — 模型固定，只改 effort
- `luckeyfaraday/auto-reasoning` — 确定性打分 + 失败升档 + 审计
- `pydantic/pydantic-ai-harness#84` — PhaseBasedEffort / HeuristicEffort
- `blackjose007-stack/adaptive-reasoning-router` — 强调在工作单边界改档

**前置条件**：先确认 DeepSeek 接口是否接受 `reasoning_effort` 及可用值。不支持就不要硬做。

---

## 5. 测试建议
- `tests/test_policy.py`：危险命令分类、strict/auto 行为、effort 阶段决策
- `tests/test_memory.py`：相似度合并、检索、忘掉
- `tests/test_md.py`：各类 Markdown → markup，非法字符转义
- 点击精度：起一个 6×4 的 24px 按钮网格，从截图坐标反算并验证落点（历史上这样发现过 int 截断 bug）

---

## 6. 不变量（改代码时必须保持）
1. worker 线程不碰 GTK
2. 截图坐标精确换算，不截断
3. Pango alpha 用数值
4. 隐藏窗口不依赖移出屏幕
5. 记忆不存内容政策类“经验”
6. 危险命令必须确认；回车=允许，Esc=拒绝
7. 清空对话不销毁欢迎页组件
8. 输出预算给足（16384），否则推理会把正文吃光
