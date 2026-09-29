#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'

on_error() {
    local status=$?
    printf '[xiuxian3] Termux 安装失败（退出码 %s，第 %s 行）：%s\n' \
        "$status" "${BASH_LINENO[0]:-?}" "${BASH_COMMAND:-?}" >&2
    printf '[xiuxian3] 可先执行 pkg update && pkg upgrade，再重试；已有文件不会被脚本删除。\n' >&2
    exit "$status"
}
trap on_error ERR

if [ -z "${PREFIX:-}" ] || [ ! -x "${PREFIX:-}/bin/pkg" ]; then
    echo "未检测到 Termux，请使用 scripts/install.sh。" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION=install
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/install.sh" --help
fi
case "${1:-}" in
    install|update|uninstall|start|pause|resume|stop|restart|status|login)
        ACTION=$1
        shift
        ;;
esac
TARGET="${1:-$HOME/xiu3}"
if (($# > 0)) && [[ "$1" != -* ]]; then
    shift
fi

missing=()
for command_name in python git clang curl; do
    command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
done
if ((${#missing[@]})); then
    if [ "${XIUXIAN3_SKIP_PKG_INSTALL:-0}" = "1" ]; then
        echo "缺少 Termux 命令：${missing[*]}；已设置 XIUXIAN3_SKIP_PKG_INSTALL=1，停止安装。" >&2
        exit 1
    fi
    echo "正在安装 Termux 依赖：${missing[*]}"
    if [ "${XIUXIAN3_SKIP_PKG_UPDATE:-0}" != "1" ]; then
        pkg update -y
    fi
    pkg install -y "${missing[@]}"
fi

VENV_PATH="${VENV_PATH:-$HOME/myenv}" "$ROOT/scripts/install.sh" "$ACTION" "$TARGET" "$@"

echo "Termux 启动: cd \"$TARGET\" && \"$HOME/myenv/bin/nb\" run"
