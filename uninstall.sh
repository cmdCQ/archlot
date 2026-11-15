#!/usr/bin/env bash
# Archlot 卸载：只删自己装的文件；配置和记忆默认保留。
set -euo pipefail

APP_ID="com.cqsomt.archlot"
PREFIX="${PREFIX:-$HOME/.local}"
PURGE=0
KEEP_CONFIG=0
FORCE=0

usage() {
    cat <<'EOF'
用法：./uninstall.sh [选项]

  --purge        同时删除配置、记忆和日志（不可恢复）
  --keep-config  保留配置，不再询问
  --prefix DIR   安装前缀（默认 ~/.local）
  --force        Archlot 正在运行时也继续
  -h, --help     显示帮助
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --purge) PURGE=1; shift ;;
        --keep-config) KEEP_CONFIG=1; shift ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
    esac
done

DATA_DIR="${ARCHLOT_DATA_DIR:-${XDG_DATA_HOME:-$PREFIX/share}/archlot}"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$PREFIX/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$PREFIX/share}/icons/hicolor/scalable/apps"

if [ ! -f "$DATA_DIR/.archlot-install" ] \
        || [ "$(cat "$DATA_DIR/.archlot-install")" != "$APP_ID" ]; then
    echo "没有找到 Archlot 安装（$DATA_DIR）。" >&2
    echo "如果用过自定义前缀，请加 --prefix。" >&2
    exit 1
fi

if pgrep -f "$DATA_DIR/archlot.py" >/dev/null 2>&1; then
    echo "Archlot 正在运行，请先退出（点关闭或结束进程）。" >&2
    if [ "$FORCE" != "1" ]; then
        echo "仍要卸载请加 --force。" >&2
        exit 1
    fi
fi

# 只删指向本安装的软链接，避免误伤同名命令。
for name in archlot archlot-setup; do
    link="$PREFIX/bin/$name"
    if [ -L "$link" ] \
            && [ "$(readlink -f "$link")" = "$DATA_DIR/bin/$name" ]; then
        rm -f "$link"
    fi
done
rm -f "$APPLICATIONS_DIR/archlot.desktop" "$ICON_DIR/archlot.svg"
rm -rf "$DATA_DIR"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

echo "已删除程序文件：$DATA_DIR"

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/archlot"
if [ "$PURGE" != "1" ] && [ "$KEEP_CONFIG" != "1" ] && [ -t 0 ]; then
    printf '同时删除配置、记忆和日志？[y/N] '
    read -r answer || answer=""
    case "$answer" in
        [Yy]*) PURGE=1 ;;
    esac
fi
if [ "$PURGE" = "1" ]; then
    rm -rf "$CONFIG_DIR"
    rm -f /tmp/archlot-app.log
    echo "已删除配置和记忆：$CONFIG_DIR"
    echo "工作区（默认 ~/archlot-workspace）未删除。"
else
    echo "配置和记忆保留在：$CONFIG_DIR"
    echo "彻底清除请运行：$0 --purge"
fi
