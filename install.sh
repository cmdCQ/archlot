#!/usr/bin/env bash
# Archlot 用户级安装：不需要 sudo，装到 ~/.local（或 --prefix）。
set -euo pipefail

APP_ID="com.cqsomt.archlot"
SRC=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)
PREFIX="${PREFIX:-$HOME/.local}"
NO_SETUP=0
FORCE=0

usage() {
    cat <<'EOF'
用法：./install.sh [选项]

  --prefix DIR   安装前缀（默认 ~/.local）
  --no-setup     装完不运行配置向导
  --force        依赖缺失或目录非空时仍然继续
  -h, --help     显示帮助
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --no-setup) NO_SETUP=1; shift ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" = "0" ]; then
    echo "请不要用 root 运行；这是用户级安装。" >&2
    exit 1
fi

DATA_DIR="${ARCHLOT_DATA_DIR:-${XDG_DATA_HOME:-$PREFIX/share}/archlot}"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$PREFIX/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$PREFIX/share}/icons/hicolor/scalable/apps"

# ── 依赖检查 ──────────────────────────────────────────────
missing=""
python3 -c 'import gi; gi.require_version("Gtk", "4.0")' 2>/dev/null \
    || missing="$missing python-gobject/gtk4"
for cmd in grim wtype wl-copy ffmpeg; do
    command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"
done
if [ -n "$missing" ]; then
    echo "缺少依赖：$missing" >&2
    echo "Arch: sudo pacman -S --needed python-gobject gtk4 at-spi2-core grim wtype wl-clipboard ffmpeg" >&2
    echo "其他发行版请安装 GTK4、PyGObject、grim、wtype、wl-clipboard、ffmpeg。" >&2
    if [ "$FORCE" != "1" ]; then
        echo "仍要继续请加 --force。" >&2
        exit 1
    fi
fi
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    echo "提示：虚拟鼠标需要 input 组，运行 sudo usermod -aG input \"$USER\" 后重新登录。"
fi

# ── 目录与覆盖保护 ────────────────────────────────────────
mkdir -p "$DATA_DIR" "$PREFIX/bin" "$APPLICATIONS_DIR" "$ICON_DIR"
if [ -e "$DATA_DIR/.archlot-install" ]; then
    :
elif [ -n "$(ls -A "$DATA_DIR" 2>/dev/null || true)" ]; then
    echo "$DATA_DIR 已存在且不是 Archlot 安装目录。" >&2
    echo "换一个 --prefix，或先手动清空它。" >&2
    exit 1
fi

# ── 复制程序 ──────────────────────────────────────────────
tar -C "$SRC" \
    --exclude=.git --exclude=.github --exclude=__pycache__ \
    --exclude='*.pyc' --exclude=dist --exclude=build --exclude=.venv \
    -cf - . | tar -C "$DATA_DIR" -xf -
printf '%s\n' "$APP_ID" > "$DATA_DIR/.archlot-install"
chmod +x "$DATA_DIR/bin/archlot" "$DATA_DIR/bin/archlot-setup" \
    "$DATA_DIR/install.sh" "$DATA_DIR/uninstall.sh"

ln -sfn "$DATA_DIR/bin/archlot" "$PREFIX/bin/archlot"
ln -sfn "$DATA_DIR/bin/archlot-setup" "$PREFIX/bin/archlot-setup"
install -m 0644 "$SRC/packaging/archlot.svg" "$ICON_DIR/archlot.svg"

cat > "$APPLICATIONS_DIR/archlot.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Archlot
GenericName=Desktop AI Assistant
Comment=A local AI agent for the niri Wayland desktop
Exec=$PREFIX/bin/archlot --toggle
Icon=$ICON_DIR/archlot.svg
Terminal=false
Categories=Utility;Accessibility;
Keywords=AI;assistant;niri;wayland;automation;desktop;
StartupNotify=false
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

echo "已安装：$DATA_DIR"
echo "命令：$PREFIX/bin/archlot [--toggle|--daemon]"
echo "向导：$PREFIX/bin/archlot-setup"
echo "卸载：$DATA_DIR/uninstall.sh [--purge]"

# ── 配置向导 ──────────────────────────────────────────────
if [ "$NO_SETUP" = "1" ]; then
    exit 0
fi
if [ -t 0 ] && [ -t 1 ]; then
    printf '现在运行配置向导（模型 / 外观 / 快捷键）？[Y/n] '
    read -r answer || answer=""
    case "$answer" in
        [Nn]*) exit 0 ;;
    esac
    "$PREFIX/bin/archlot-setup"
else
    echo "非交互安装，跳过向导。之后运行：$PREFIX/bin/archlot-setup"
fi
