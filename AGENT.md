# Archlot 开发守则

本文件是改代码时的唯一规范源。`CLAUDE.md`、`README.md` 只做介绍，冲突时以这里为准。

## 架构

```
archlot.py                入口 + 依赖接线
core/                     与界面、对话无关的底层
  config.py               配置、路径、原子写 JSON
  contracts.py            ToolResult / ToolContext / UI Protocol
  system.py               子进程、niri IPC、屏幕/窗口/图片
  llm.py                  DeepSeek 流式客户端
  memory.py               SQLite FTS5 长期记忆
agent/                    一轮对话怎么跑
  loop.py                 轮次、预算、队列、取消、记忆后处理
  history.py              MessageHistory（配对/裁剪/截图）
  prompts.py              提示词字符串
tools/                    动作怎么执行
  __init__.py             Tools 调度 + HANDLERS
  schema.py               工具 JSON schema
  policy.py               allow / ask / deny
  files.py                shell、读写、列目录
  desktop.py              截图、鼠标、键盘、窗口、面板
  recall.py               memory 工具
  devices.py              uinput、wtype、剪贴板
ui/                       唯一碰 GTK 的地方
  __init__.py             对外只暴露 Panel
  panel.py                窗口、几何、动效、确认框、线程边界
  chat.py                 工具卡片文案
  markdown.py             Markdown → Pango
  sound.py                提示音
```

依赖只能向下：

```
archlot.py ──► agent / tools / ui
agent      ──► core
tools      ──► core
ui         ──► core
```

`core/` 不 import 上层；`agent/`、`tools/`、`ui/` 互不 import；只有 `archlot.py` 认识全部模块。

## 硬规矩

1. **GTK 只在 `ui/` 里碰。** `agent/`、`tools/`、`core/` 不 import gi。
   跨线程更新界面只能通过 `UI` 端口；`Panel` 自己用 `_ui` / `_main_sync` 切主线程。
   主线程禁止跑 `niri`、`grim`、`wtype`、shell 等子进程；要跑就丢 worker。

2. **不要在 UI 线程里 sleep 等同步。** worker 要等主线程结果用 `_main_sync`；
   等合成器处理显隐用 `_main_sync_after`。不要用 `time.sleep` 猜时序。

3. **策略只有一个源：`tools/policy.py`。** 工具里不许再写“这个命令危不危险”；
   系统提示词里的策略说明由 `Policy.describe()` 生成，不许在 `prompts.py` 里另写一套。
   “策略拒绝（denied）”和“执行失败（exception）”必须分开，前者不触发经验反思。

4. **消息历史只能由 `agent/history.py` 改。** 必须保持：
   - assistant 的每个 `tool_calls` 后面紧跟对应 `tool` 消息；
   - 裁剪只能切在纯字符串的 user 消息上，不能切断工具调用组；
   - 截图消息是列表 content 的 user 消息，不算新一轮的起点；
   - 思考模式模型带 `tool_calls` 时必须回传 `reasoning_content`（空串可以）。

5. **工具结果必须结构化。** 返回 `ToolResult`，失败带 `error_kind`
   （`bad_args` / `denied` / `exception` / `not_found` / `input` / ...）。
   不许再用“结果里含有‘失败’两个字”判断成败。

6. **配置和路径只从 `core/config.py` 取。** 不在别处硬编码 `~/.config/archlot`；
   写 JSON 用 `atomic_write_json`。

7. **循环必须有预算。** `max_steps`、`max_turn_seconds`、`max_tool_seconds`
   都在 `Config` 里；新增循环必须能取消、能超时。

8. **输入框固定 `im-module=fcitx5`**。GTK 4.24 的 Wayland text-input 在中文
   preedit 时光标不跟随，走 fcitx5 的 GTK 模块可以避开；不要删掉这个属性。

9. **UI 细节不变量**见 `CLAUDE.md`：非 resizable 窗口改尺寸要先压最小尺寸；
   透明度作用在 `.root` 的 CSS alpha，不用 `win.set_opacity`；
   截图坐标必须浮点换算，不许 `int()` 截断；`wl-copy` 要丢管道；
   Pango alpha 用 0–65536；niri 会夹取浮动窗口，隐藏靠淡出 + unmap。

## 记忆

- `Memory.search` 查不到就返回空，不要回退到“最近事实”；无关记忆不能进每轮上下文。
- 自动抽取只记用户明确说过的稳定信息。助手窗口的临时位置、尺寸、当前透明度状态、
  进程号、一次性任务结果、工具支持哪些参数，都不进事实库。
- 自动抽取的“偏好”必须能在用户原话里找到长期信号（以后 / 每次 / 记住 / 别再…）；
  一次性的情绪或评价不要推断成偏好。
- `profile.md` 放每轮都需要的稳定档案；事实库只放需要检索的条目。

## 加一个工具

1. 在 `tools/files.py`、`tools/desktop.py` 或 `tools/recall.py` 写
   `def name(tools, args) -> ToolResult`。
2. 在 `tools/schema.py` 的 `TOOLS` 里加 schema。
3. 在 `tools/__init__.py` 的 `HANDLERS` 里登记。
4. 涉及危险操作时只改 `Policy.review`，不要在工具里问确认。
5. 跑 `tests/test_tools.py`，它会检查 schema 和 HANDLERS 是否一一对应。

## 加一个界面行为

1. agent 需要通知界面：先在 `core/contracts.py` 的 `UI` 端口加方法。
2. 在 `ui/panel.py` 实现；worker 调用方法内部用 `_ui` 切主线程。
3. 界面需要主动找 agent（发送、取消、清空）：通过 `panel.agent`，不要反向 import。

## 验证

```bash
python -m compileall -q core agent tools ui archlot.py
python -m unittest discover -s tests -t .
```

没有 pytest / ruff，不要引入。GUI 冒烟需要重启旧进程后跑 `bin/archlot`；
旧进程不退出时，同 `APP_ID` 的新实例只会把命令转发给旧实例。

## 不要加

- 事件总线、依赖注入框架、provider 适配层
- 为单一实现写的抽象基类
- 数据库 migration / FTS 触发器
- 为了让主线程“等一等”而加的 sleep
- 在 prompt 和 policy 各写一份安全规则
- 没有明确职责的新顶层包
