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
exec bash "$ROOT/scripts/onekey.sh" "$@"
