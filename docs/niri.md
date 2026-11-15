# Archlot × niri

Archlot 是一个 GTK4 窗口，niri 负责把它摆放、裁剪和模糊。两边各管一件事：

- **Archlot 管自己长什么样**：背景色、透明度、主色、圆角、字号。
  透明度是 `.root` 的 CSS alpha。
- **niri 管窗口在桌面上的行为**：浮动、位置、圆角裁剪、背景模糊。

> **不要**在 niri 的 window-rule 里写 `opacity`。niri 的透明度和窗口自身的
> CSS alpha 会叠乘，0.8 × 0.8 实际只剩 0.64。Archlot 已经用 CSS 控制透明度。

## 1. 窗口规则

`~/.config/niri/config.kdl` 里加：

```kdl
window-rule {
    match app-id=r#"^com\.cqsomt\.archlot$"#
    open-floating true
    default-floating-position x=18 y=0 relative-to="top-right"
    geometry-corner-radius 18
    clip-to-geometry true
    background-effect {
        blur true
        xray true
        noise 0.020
    }
}
```

- `geometry-corner-radius` + `clip-to-geometry true` 让窗口圆角真正裁掉四角。
- `background-effect` 需要 **niri 26.04 或更新版本**。老版本删掉整段即可。
- `xray true` 让模糊透到壁纸而不是下层窗口；想要普通模糊就设 `false`。
- 保存后 niri 自动重载，不需要重启。

如果 Archlot 的圆角改过，`geometry-corner-radius` 应该跟它一致。
不用手抄——让 Archlot 自己生成：

```text
appearance(action="niri")
```

它会把当前外观对应的 window-rule 打出来，直接贴进 niri 配置。

## 2. Copilot 键

`archlot-setup`（`--only hotkey`）会自动生成并写入这一节；检测到已有 Archlot
规则时不会重复写，写入前会备份 `config.kdl`。下面是手动配置的版本。

很多笔记本键盘上的 Copilot 键在 Wayland 里报告为 `XF86TouchpadOff`。
niri 按**基础层符号**匹配按键，所以绑定要写 `XF86TouchpadOff` 这个符号本身，
不能写成 `Copilot`；这台机器上实测还要带上 `Mod+Shift` 前缀。

先放一个包装脚本 `~/.local/bin/ai`：

```bash
#!/usr/bin/env bash
exec "$HOME/projects/archlot/bin/archlot" --toggle
```

```bash
chmod +x ~/.local/bin/ai
```

然后在 niri 配置里加：

```kdl
binds {
    Mod+Shift+XF86TouchpadOff repeat=false hotkey-overlay-title="AI 助手" {
        spawn "/home/你的用户名/.local/bin/ai";
    }
}
```

niri 的 `spawn` 不展开 `~`，所以要写绝对路径。Archlot 自己也是单实例：
`--toggle` 会唤醒已驻留的面板，不会开第二个。

## 3. 外观预设

`appearance(action="preset", preset="...")` 可直接切换：

| 预设 | 感觉 |
|---|---|
| `default` | 紫罗兰，0.80 透明，无模糊 |
| `midnight` | 深蓝紫，带模糊 |
| `warm` | 暖橙，圆角小一点 |
| `cyan` | 青蓝，0.78 透明 |
| `mono` | 近黑灰，不透明一些，无模糊 |
| `rose` | 粉紫 |

改完外观后再跑一次 `appearance(action="niri")`，把新的
`geometry-corner-radius` 同步回 niri 规则即可。

## 4. 调试

```bash
niri msg windows                 # 找到 Archlot 的 app_id 和 id
niri msg layers                  # 确认没有和 layer-shell 冲突
journalctl --user -u niri -f     # 看配置解析错误
```

App ID 固定为 `com.cqsomt.archlot`，定义在 `core/config.py`。
