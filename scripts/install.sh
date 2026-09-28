#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION=install
TARGET=""
VENV="${VENV_PATH:-$HOME/myenv}"
PYTHON="${PYTHON_BIN:-python3}"
START=0
YES=0

usage() {
    cat <<'EOF'
用法：scripts/install.sh <命令> [目标宿主目录] [选项]

命令：
  install              安装或修复宿主（默认命令）
  update               更新插件依赖和缺少的内容文件
  uninstall            卸载宿主目录（必须额外传 --yes）
  start|pause|resume|stop|restart|status
                       控制安装后由 xiu3 管理的 nb run 进程

选项：
  --python PATH       指定系统 Python（默认 python3）
  --venv PATH         指定虚拟环境（默认 $HOME/myenv）
  --index-url URL     指定 pip 镜像，只影响本次安装
  --run               安装后立即执行 nb run（兼容旧用法）
  --yes               确认 uninstall，不删除共享虚拟环境
  -h, --help          显示帮助

脚本不会删除目标目录，不会覆盖已有 bot.py、pyproject.toml、.env 或 data/*.json。
EOF
}

log() { printf '[xiuxian3] %s\n' "$*"; }
warn() { printf '[xiuxian3] 警告：%s\n' "$*" >&2; }
fail() { printf '[xiuxian3] 错误：%s\n' "$*" >&2; exit 1; }

on_error() {
    local status=$?
    printf '[xiuxian3] 安装失败（退出码 %s，第 %s 行）：%s\n' \
        "$status" "${BASH_LINENO[0]:-?}" "${BASH_COMMAND:-?}" >&2
    printf '[xiuxian3] 可保留当前目录后重试；若是网络问题，可设置 PIP_INDEX_URL 或传入 --index-url。\n' >&2
    exit "$status"
}
trap on_error ERR

case "${1:-}" in
    install|update|uninstall|start|pause|resume|stop|restart|status)
        ACTION=$1
        shift
        ;;
esac

while (($#)); do
    case "$1" in
        --python)
            (($# >= 2)) || fail "--python 需要一个路径"
            PYTHON=$2
            shift 2
            ;;
        --venv)
            (($# >= 2)) || fail "--venv 需要一个路径"
            VENV=$2
            shift 2
            ;;
        --index-url)
            (($# >= 2)) || fail "--index-url 需要一个 URL"
            export PIP_INDEX_URL=$2
            shift 2
            ;;
        --run)
            START=1
            shift
            ;;
        --yes)
            YES=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -* )
            fail "未知选项：$1（使用 --help 查看用法）"
            ;;
        *)
            [ -z "$TARGET" ] || fail "只能指定一个目标宿主目录"
            TARGET=$1
            shift
            ;;
    esac
done

TARGET="${TARGET:-$ROOT/nonebot-bot}"
if [ "$ACTION" = update ] && [ ! -d "$TARGET" ]; then
    fail "更新目标不存在：$TARGET；请先执行 install。"
fi
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd -P)"
VENV="$(mkdir -p "$(dirname "$VENV")" && cd "$(dirname "$VENV")" && pwd -P)/$(basename "$VENV")"

if [[ "$ACTION" != install && "$ACTION" != update ]]; then
    control_args=()
    ((YES)) && control_args+=(--yes)
    exec "$ROOT/scripts/control.sh" "$TARGET" "$VENV" "$ROOT" "$ACTION" "${control_args[@]}"
fi

[ -f "$ROOT/pyproject.toml" ] || fail "找不到项目 pyproject.toml：$ROOT"
[ -f "$ROOT/examples/nonebot/bot.py" ] || fail "找不到宿主模板：$ROOT/examples/nonebot/bot.py"
[ -d "$ROOT/data" ] || fail "找不到内容目录：$ROOT/data"

command -v "$PYTHON" >/dev/null 2>&1 || fail "找不到 $PYTHON。请安装 Python 3.11+，或使用 --python 指定路径。"
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "需要 Python 3.11 或更高版本；当前为 $($PYTHON --version 2>&1)"
"$PYTHON" -m venv --help >/dev/null 2>&1 \
    || fail "当前 Python 缺少 venv 模块。Linux 请安装 python3-venv，Termux 请执行 pkg install python。"

LOCK="$VENV.xiuxian3-install.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    fail "检测到另一个安装进程正在使用 $VENV；确认无安装进程后删除 $LOCK 再重试。"
fi
cleanup() { rmdir "$LOCK" 2>/dev/null || true; }
trap cleanup EXIT

VENV_PY="$VENV/bin/python"
VENV_NB="$VENV/bin/nb"
if [ -e "$VENV" ] && [ ! -x "$VENV_PY" ]; then
    fail "虚拟环境目录存在但不可用：$VENV；不会自动删除，请备份后手动处理。"
fi
if [ ! -x "$VENV_PY" ]; then
    log "创建虚拟环境：$VENV"
    if [ -n "${PREFIX:-}" ]; then
        # Termux ships Android-compatible wheels in its prefix.  Exposing
        # them avoids replacing binary packages with incompatible PyPI wheels.
        "$PYTHON" -m venv --system-site-packages "$VENV"
    else
        "$PYTHON" -m venv "$VENV"
    fi
fi

retry() {
    local attempt=1
    local max_attempts=3
    while :; do
        if "$@"; then
            return 0
        fi
        if ((attempt >= max_attempts)); then
            return 1
        fi
        warn "命令失败，将在 ${attempt} 秒后重试（$attempt/$max_attempts）：$*"
        sleep "$attempt"
        attempt=$((attempt + 1))
    done
}

"$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV_PY" -m pip --version >/dev/null 2>&1 \
    || fail "虚拟环境没有 pip：$VENV_PY。请确认 Python 安装包含 ensurepip。"

log "升级 pip、setuptools 和 wheel"
retry "$VENV_PY" -m pip install --upgrade pip setuptools wheel \
    || fail "pip 基础工具安装失败。请检查网络、代理、证书或使用 --index-url 指定镜像。"

log "安装 NoneBot、适配器和本插件（普通 wheel 安装）"
project_pip_args=(--no-build-isolation)
if [ "$ACTION" = update ]; then
    project_pip_args=(--upgrade --no-build-isolation)
    if [ -z "${PREFIX:-}" ]; then
        project_pip_args=(--upgrade --upgrade-strategy eager --no-build-isolation)
    fi
fi
retry "$VENV_PY" -m pip install "${project_pip_args[@]}" "$ROOT[nonebot,onebot,qq]" \
    || fail "项目依赖安装失败。保留的宿主目录和虚拟环境可以直接重试。"

copy_if_missing() {
    local source=$1
    local destination=$2
    if [ ! -e "$destination" ]; then
        mkdir -p "$(dirname "$destination")"
        cp "$source" "$destination"
        log "写入 $destination"
    else
        log "保留已有文件 $destination"
    fi
}

copy_if_missing "$ROOT/examples/nonebot/bot.py" "$TARGET/bot.py"
copy_if_missing "$ROOT/examples/nonebot/pyproject.toml" "$TARGET/pyproject.toml"
copy_if_missing "$ROOT/examples/nonebot/.env.example" "$TARGET/.env"

while IFS= read -r -d '' source; do
    relative="${source#"$ROOT/data/"}"
    copy_if_missing "$source" "$TARGET/data/$relative"
done < <(find "$ROOT/data" -type f -name '*.json' -print0)

mkdir -p "$TARGET/.xiuxian3"
cp "$ROOT/scripts/control.sh" "$TARGET/.xiuxian3/control.sh"
chmod +x "$TARGET/.xiuxian3/control.sh"

CONTROL_BIN="$TARGET/xiu3"
target_q=$(printf '%q' "$TARGET")
venv_q=$(printf '%q' "$VENV")
root_q=$(printf '%q' "$ROOT")
write_control_launcher() {
    local launcher=$1
    cat > "$launcher" <<EOF
#!/usr/bin/env bash
action="\${1:-status}"
if ((\$#)); then shift; fi
exec "$TARGET/.xiuxian3/control.sh" $target_q $venv_q $root_q "\$action" "\$@"
EOF
    chmod +x "$launcher"
}
write_control_launcher "$CONTROL_BIN"

CONTROL_DIR="$HOME/.local/bin"
if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ] && [ -w "$PREFIX/bin" ]; then
    CONTROL_DIR="$PREFIX/bin"
fi
if mkdir -p "$CONTROL_DIR" 2>/dev/null && write_control_launcher "$CONTROL_DIR/xiu3" 2>/dev/null; then
    CONTROL_COMMAND="$CONTROL_DIR/xiu3"
else
    CONTROL_COMMAND="$CONTROL_BIN"
    warn "无法写入公共命令目录；请使用 $CONTROL_BIN，或将 $TARGET 加入 PATH。"
fi

log "校验已安装包、NoneBot 入口和 JSON 内容"
"$VENV_PY" -c 'import nonebot; import nonebot_plugin_xiuxian_3'
"$VENV_NB" --help >/dev/null 2>&1 \
    || fail "nb 命令未安装：$VENV_NB"
"$VENV_PY" - "$TARGET/data" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
files = sorted(root.rglob("*.json"))
if not files:
    raise SystemExit("data 目录没有 JSON 内容")
for path in files:
    with path.open(encoding="utf-8") as handle:
        json.load(handle)
print(f"已校验 {len(files)} 个 JSON 文件")
PY

if ((START)); then
    log "启动宿主：cd $TARGET && $VENV_NB run"
    cd "$TARGET"
    exec "$VENV_NB" run
fi

cat <<EOF

安装完成。
宿主目录：$TARGET
虚拟环境：$VENV
控制命令：$CONTROL_COMMAND start|pause|resume|stop|restart|status|update|uninstall
宿主内命令：$CONTROL_BIN start
更新命令：$CONTROL_COMMAND update
EOF
