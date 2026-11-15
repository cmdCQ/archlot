# Archlot

住在 niri 桌面上的本地 AI 助手。GTK4 + Python，DeepSeek（OpenAI 兼容）后端。

## 快速开始

```bash
# 启动（--toggle 会唤出/收起）
bin/archlot --toggle

# 配置
~/.config/archlot/config.json

# 运行日志
/tmp/archlot-app.log      # 每轮 llm / 工具耗时、记忆写入
/tmp/opencode/archlot.log # stderr（CSS 警告、traceback）
```

编程接口（用 Copilot 键或脚本调）：

```bash
bin/archlot              # 显示
bin/archlot --toggle     # 切换
bin/archlot --daemon     # 只驻留，不显示
```

## 架构（当前）

```
archlot.py   ~1650 行  应用入口 + UI + agent 循环（待拆）
tools.py     ~840 行   12 个工具的实现与 schema
memory.py    ~390 行   本地长期记忆（SQLite FTS5 + Markdown）
llm.py       ~100 行   DeepSeek 流式客户端
md.py        ~80 行    Markdown → Pango markup
style.css    ~380 行   面板视觉与动效
```

**已知的架构问题**：`archlot.py` 太大；自动审查规则写在 `tools.py` 里；思考强度策略还没落地。
目标是引入 `policy.py` 统一“这一步怎么对待”（是否确认、想多深），并拆出 `ui/panel.py` 与 `agent.py`。

## 关键设计约束（改代码前必读）

1. **GTK 不是线程安全的**。工具在 worker 线程执行，任何 `Gtk.*` 调用都必须 `GLib.idle_add`。
   违反会直接段错误（曾经发生过）。
2. **窗口尺寸非 resizable**。`root.set_size_request(w, h)` 控制窗体大小；缩小前要先把最小尺寸压到目标以下，
   否则 GTK 保留旧尺寸。
3. **透明度作用在背景 alpha**（控件级 CssProvider），不是 `win.set_opacity`。
   `win.set_opacity` 只用于收起淡出。
4. **截图坐标到屏幕坐标**：`click/move_mouse` 传的是截图像素坐标，`Tools._to_screen` 按
   `逻辑尺寸/图片尺寸` 精确换算。不要 `int()` 截断截图坐标（曾造成系统性偏差）。
   截图默认 0.8 倍；小目标建议 1.0。
5. **Pango markup**：`alpha` 只能用 0–65536 的数值；`alpha="0%"` 会解析失败并让整条消息渲染不出来。
6. **niri 会夹取浮动窗口**，不能真正移出屏幕。隐藏用“淡出 + unmap”，不要依赖位移。
7. **`wl-copy` 会 fork**。用 `subprocess.run(..., stdout=DEVNULL, stderr=DEVNULL)`，
   否则管道不关会卡到超时。
8. **noVNC / KVM 网页控制台不认 `wtype` 的虚拟键盘**，输入会丢字或变数字。
   这种情况用 `type_text(method="keys")`（uinput 真实键码）。

## 工具

`run_shell` `read_file` `write_file` `list_dir` `screenshot` `click` `move_mouse`
`scroll` `type_text` `press_key` `list_windows` `focus_window` `panel` `memory`

- 默认工作区 `~/archlot-workspace`，也是 shell 的 cwd
- 工作区外写入默认放行但会在结果里标注；`confirm_mode=strict` 时才询问
- 危险命令（sudo、mkfs、dd、关机、卸载包、删系统目录）一律弹确认（回车允许 / Esc 拒绝）

## 记忆

- `~/.config/archlot/memory/profile.md` 用户档案（每轮注入）
- `facts.db` 事实库（FTS5，tags 含 偏好/环境/项目/经验），启动时本地聚类去重
- `notes/YYYY-MM.md` 会话小结
- 失败反思会自动写“经验”，但排除内容政策类结论

## 视觉

- 右侧竖栏，默认 380×880，贴右居中，可拖标题栏移动
- 默认背景 alpha 0.8，`panel(opacity=...)` 可调（1.0 = 完全不透明）
- 状态呼吸：待机 5.5s、干活 1.5s、出错闪红
- 流式光标、消息上滑入场、清空淡出、平滑滚动
- 声效可关：`"sound_effects": false`

## 待办（按优先级）

1. **合并策略层**：`policy.py` 统一自动审查 + 思考强度，配置迁到 `policy` 块
2. **拆文件**：`ui/panel.py`、`agent.py`，`archlot.py` 只留入口
3. **思考强度自适应**：按阶段（规划/执行/验证）降档，失败立即升档；默认关，先 A/B
4. 测试：`tests/` 覆盖 policy、记忆去重、Markdown、坐标换算
5. 清理：`noise.svg`、`style.css.bak`、`__pycache__`

详细交接见 `docs/HANDOFF.md`。
