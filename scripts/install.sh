#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION=install
TARGET=""
SOURCE="$ROOT"
SOURCE_MODE=source
MIRROR=direct
MIRROR_URL=""
VENV="${VENV_PATH:-$HOME/myenv}"
PYTHON="${PYTHON_BIN:-}"
INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
START=0
YES=0
LOGIN_ARGS=()

usage() {
    cat <<'EOF'
用法：scripts/install.sh <命令> [选项]

命令：
  install              安装或修复宿主（默认命令）
  update               更新插件依赖和缺少的内容文件
  uninstall            卸载宿主目录（必须额外传 --yes）
  start|stop|restart|status|logs|login
                       控制安装后由 xiu3 管理的 nb run 进程

选项：
  --target PATH       宿主目录（默认项目目录下的 xiu3）
  --source PATH       插件源码目录（默认当前 checkout）
  --source-mode MODE  auto、release 或 source
  --mirror MODE       direct、accelerated 或 custom
  --mirror-url URL    自定义 Release 归档或 Git 仓库地址
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
    install|update|uninstall|start|pause|resume|stop|restart|status|logs|login)
        ACTION=$1
        shift
        ;;
esac

while (($#)); do
    case "$1" in
        --target)
            (($# >= 2)) || fail "--target 需要一个路径"
            TARGET=$2
            shift 2
            ;;
        --source)
            (($# >= 2)) || fail "--source 需要一个路径"
            SOURCE=$2
            shift 2
            ;;
        --source-mode)
            (($# >= 2)) || fail "--source-mode 需要一个值"
            SOURCE_MODE=$2
            shift 2
            ;;
        --mirror)
            (($# >= 2)) || fail "--mirror 需要一个值"
            MIRROR=$2
            shift 2
            ;;
        --mirror-url)
            (($# >= 2)) || fail "--mirror-url 需要一个 URL"
            MIRROR_URL=$2
            shift 2
            ;;
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
            INDEX_URL=$2
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
        --timeout|--interval)
            (($# >= 2)) || fail "$1 需要一个值"
            LOGIN_ARGS+=("$1" "$2")
            shift 2
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

TARGET="${TARGET:-$ROOT/xiu3}"
if [ -d "$SOURCE" ]; then
    SOURCE="$(cd "$SOURCE" && pwd -P)"
else
    mkdir -p "$(dirname "$SOURCE")"
    SOURCE="$(cd "$(dirname "$SOURCE")" && pwd -P)/$(basename "$SOURCE")"
fi
case "$SOURCE_MODE" in auto|release|source) ;; *) fail "不支持的源码模式：$SOURCE_MODE" ;; esac
case "$MIRROR" in direct|accelerated|custom) ;; *) fail "不支持的镜像模式：$MIRROR" ;; esac

control_action=0
case "$ACTION" in start|stop|restart|status|logs|login|uninstall|pause|resume) control_action=1 ;; esac
if ((control_action)); then
    TARGET="$(cd "$TARGET" 2>/dev/null && pwd -P)" || fail "找不到宿主目录：$TARGET"
else
    mkdir -p "$(dirname "$TARGET")"
    TARGET="$(cd "$(dirname "$TARGET")" && pwd -P)/$(basename "$TARGET")"
fi
VENV="$(mkdir -p "$(dirname "$VENV")" && cd "$(dirname "$VENV")" && pwd -P)/$(basename "$VENV")"

if ((control_action)); then
    control_args=("$ACTION" --target "$TARGET" --source "$SOURCE" --source-mode "$SOURCE_MODE" --mirror "$MIRROR" --venv "$VENV")
    [ -n "$MIRROR_URL" ] && control_args+=(--mirror-url "$MIRROR_URL")
    ((YES)) && control_args+=(--yes)
    control_args+=("${LOGIN_ARGS[@]}")
    exec "$ROOT/scripts/control.sh" "${control_args[@]}"
fi

if [ "$ACTION" = update ] && [ ! -d "$TARGET" ]; then
    fail "更新目标不存在：$TARGET；请先执行 install。"
fi
mkdir -p "$TARGET"

if [[ "$SOURCE_MODE" == release ]]; then
    release_args=("$ACTION" --target "$TARGET" --source "$SOURCE" --source-mode release --mirror "$MIRROR" --venv "$VENV")
    [ -n "$MIRROR_URL" ] && release_args+=(--mirror-url "$MIRROR_URL")
    ((YES)) && release_args+=(--yes)
    exec "$ROOT/scripts/onekey.sh" "${release_args[@]}"
fi

if [ "$SOURCE" != "$ROOT" ]; then
    [ -f "$SOURCE/scripts/install.sh" ] && [ -f "$SOURCE/pyproject.toml" ] || fail "--source 不是有效的 xiu3 checkout：$SOURCE"
    rerun_args=("$ACTION" --target "$TARGET" --source "$SOURCE" --source-mode source --mirror "$MIRROR" --venv "$VENV" --index-url "$INDEX_URL")
    ((YES)) && rerun_args+=(--yes)
    exec bash "$SOURCE/scripts/install.sh" "${rerun_args[@]}"
fi

if [ -z "$PYTHON" ]; then
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && \
            "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            PYTHON=$candidate
            break
        fi
    done
    PYTHON="${PYTHON:-python3}"
fi

[ -f "$ROOT/pyproject.toml" ] || fail "找不到项目 pyproject.toml：$ROOT"
[ -f "$ROOT/requirements.txt" ] || fail "找不到项目 requirements.txt：$ROOT"
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
retry "$VENV_PY" -m pip install --index-url "$INDEX_URL" --upgrade pip setuptools wheel \
    || fail "pip 基础工具安装失败。请检查网络、代理、证书或使用 --index-url 指定镜像。"

log "配置虚拟环境使用 pip 镜像：$INDEX_URL"
"$VENV_PY" -m pip config --site set global.index-url "$INDEX_URL" >/dev/null \
    || warn "无法写入虚拟环境 pip 配置，将只对本次安装使用指定镜像。"

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

log "从 requirements.txt 安装 nb-cli"
retry "$VENV_PY" -m pip install --upgrade --index-url "$INDEX_URL" -r "$ROOT/requirements.txt" \
    || fail "nb-cli 安装失败。保留的宿主目录和虚拟环境可以直接重试。"
export PIP_INDEX_URL="$INDEX_URL"

component_action=install
[ "$ACTION" != update ] || component_action=update
install_nb_component() {
    local group=$1 name=$2
    local install_args=()
    if [ "$component_action" = install ] && [ "$group" = adapter ]; then
        install_args+=(--no-restrict-version)
    fi
    log "通过 nb $group $component_action 安装 $name"
    retry "$VENV_NB" --cwd "$TARGET" --python "$VENV_PY" "$group" "$component_action" "${install_args[@]}" "$name" \
        || fail "nb $group $component_action $name 失败。请检查 NoneBot CLI 的网络错误后重试。"
}
install_nb_component adapter "QQ"
install_nb_component adapter "OneBot V11"
install_nb_component driver "FastAPI"
install_nb_component driver "HTTPX"
install_nb_component driver "websockets"
install_nb_component driver "AIOHTTP"

log "安装修仙插件本身，不重复解析 CLI 已安装的运行依赖"
project_pip_args=(--no-build-isolation --no-deps --index-url "$INDEX_URL")
if [ "$ACTION" = update ]; then project_pip_args=(--upgrade "${project_pip_args[@]}"); fi
retry "$VENV_PY" -m pip install "${project_pip_args[@]}" "$ROOT" \
    || fail "修仙插件安装失败。保留的宿主目录和虚拟环境可以直接重试。"

while IFS= read -r -d '' source; do
    relative="${source#"$ROOT/data/"}"
    copy_if_missing "$source" "$TARGET/data/$relative"
done < <(find "$ROOT/data" -type f -name '*.json' -print0)

mkdir -p "$TARGET/.xiuxian3"
cp "$ROOT/scripts/control.sh" "$TARGET/.xiuxian3/control.sh"
cp "$ROOT/scripts/qq_login.py" "$TARGET/.xiuxian3/qq_login.py"
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
exec "$TARGET/.xiuxian3/control.sh" "\$action" --target $target_q --venv $venv_q --source $root_q "\$@"
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
"$VENV_PY" -c 'import importlib.metadata; import nonebot; import nonebot.adapters.qq; import nonebot.adapters.onebot.v11; import nonebot_plugin_xiuxian_3; importlib.metadata.version("nb-cli")'
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
控制命令：$CONTROL_COMMAND install|update|uninstall|start|stop|restart|status|logs|login
宿主内命令：$CONTROL_BIN start
更新命令：$CONTROL_COMMAND update
QQ 官方绑定：$CONTROL_COMMAND login
EOF
