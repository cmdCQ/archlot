# 安装、更新与卸载

Archlot 默认是**用户级安装**：不需要 sudo，不碰系统目录，卸载只删自己装的文件。

## 依赖

Arch:

```bash
sudo pacman -S --needed python-gobject gtk4 at-spi2-core grim wtype wl-clipboard ffmpeg
sudo usermod -aG input "$USER"   # 虚拟鼠标；改完重新登录
```

其他发行版需要 GTK4、PyGObject、grim、wtype、wl-clipboard、ffmpeg。

## 安装

```bash
git clone https://github.com/cmdCQ/archlot.git
cd archlot
./install.sh
```

想装到别的前缀（默认 `~/.local`）：

```bash
./install.sh --prefix ~/apps
```

装完会询问是否运行 `archlot-setup`。跳过用 `--no-setup`，之后随时可以再跑。

向导开头是一页快速上手（功能展示 + 基本按键 + 外观说明），之后依次配置模型、
默认外观和快捷键。`archlot-setup --only tutorial` 可随时重看，
`--no-tutorial` 可跳过。

### 装了哪些文件

| 路径 | 内容 |
|---|---|
| `~/.local/share/archlot/` | 程序和资源（含卸载脚本） |
| `~/.local/bin/archlot` | 启动命令（软链接） |
| `~/.local/bin/archlot-setup` | 配置向导（软链接） |
| `~/.local/share/applications/archlot.desktop` | 桌面入口 |
| `~/.local/share/icons/hicolor/scalable/apps/archlot.svg` | 图标 |

运行数据在 `~/.config/archlot/`；工作区默认 `~/archlot-workspace`。

## 更新

```bash
cd archlot
git pull
./install.sh --no-setup
```

安装脚本会覆盖程序文件，但不会碰 `~/.config/archlot`。

## 卸载

```bash
./uninstall.sh
```

只删除程序、命令、桌面入口和图标，保留配置与记忆。运行时会先确认一次；
在非交互环境里默认保留。

想连配置、记忆和日志一起清掉：

```bash
./uninstall.sh --purge
```

工作区（默认 `~/archlot-workspace`）始终保留，因为里面可能是你的文件。

卸载脚本会先核对安装标记，只删除指向本安装的软链接；不会误删同名的其他命令。

## Arch 包

`packaging/PKGBUILD` 是 `archlot-git` 模板：

```bash
cd packaging
makepkg -si
```

程序装到 `/usr/share/archlot`，`/usr/bin/archlot` 和
`/usr/bin/archlot-setup` 是指向它的软链接。卸载用 `pacman -R archlot-git`。
配置仍由配置向导写入用户目录。

## 直接跑源码

不安装也能用：

```bash
bin/archlot --toggle
bin/archlot-setup
```

## 常见问题

**`archlot: command not found`**：把 `~/.local/bin` 加进 `PATH`，重新登录或
`export PATH="$HOME/.local/bin:$PATH"`。

**鼠标点击没反应**：确认在 `input` 组里（`id -nG`），改过组之后要重新登录。

**面板起不来**：先跑 `python3 -c 'import gi; gi.require_version("Gtk", "4.0")'`
看 GTK4 是否可用；日志在 `/tmp/archlot-app.log`。
