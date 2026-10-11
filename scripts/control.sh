#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

TARGET=${XIUXIAN3_TARGET:-$HOME/xiu3}
VENV=${VENV_PATH:-$HOME/myenv}
SOURCE_ROOT=${XIUXIAN3_SOURCE_DIR:-}
ACTION=status
SOURCE_MODE=auto
MIRROR=direct
MIRROR_URL=
LOG_LINES=80
YES=0
LOGIN_ARGS=()

usage() {
    cat <<'EOF'
用法：control.sh <install|update|uninstall|start|stop|restart|status|logs|login> [选项]

选项：
  --target PATH       宿主目录（默认 $HOME/xiu3）
  --source PATH       插件源码目录
  --source-mode MODE  auto、release 或 source
  --mirror MODE       direct、accelerated 或 custom
  --mirror-url URL    自定义 Release 归档或 Git 仓库地址
  --venv PATH         Python 虚拟环境（默认 $HOME/myenv）
  --lines N           logs 显示最近 N 行（默认 80）
  --yes               确认卸载宿主及其 SQLite 数据
EOF
}

if (($#)) && [[ "$1" =~ ^(install|update|uninstall|start|stop|restart|status|logs|login)$ ]]; then
    ACTION=$1
    shift
elif (($# >= 4)) && [[ "$1" != -* ]]; then
    # Compatibility with launchers generated before the named CLI was added.
    TARGET=$1
    VENV=$2
    SOURCE_ROOT=$3
    ACTION=$4
    shift 4
fi

while (($#)); do
    case "$1" in
        --target|--source|--source-mode|--mirror|--mirror-url|--venv|--lines)
            (($# >= 2)) || { printf '[xiu3] %s 需要一个值\n' "$1" >&2; exit 2; }
            key=$1
            value=$2
            case "$key" in
                --target) TARGET=$value ;;
                --source) SOURCE_ROOT=$value ;;
                --source-mode) SOURCE_MODE=$value ;;
                --mirror) MIRROR=$value ;;
                --mirror-url) MIRROR_URL=$value ;;
                --venv) VENV=$value ;;
                --lines) LOG_LINES=$value ;;
            esac
            shift 2
            ;;
        --yes) YES=1; shift ;;
        --timeout|--interval)
            (($# >= 2)) || { printf '[xiu3] %s 需要一个值\n' "$1" >&2; exit 2; }
            LOGIN_ARGS+=("$1" "$2")
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) printf '[xiu3] 未知参数：%s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ "$LOG_LINES" =~ ^[1-9][0-9]*$ ]] || { printf '[xiu3] --lines 必须是正整数\n' >&2; exit 2; }

TARGET=$(cd "$TARGET" 2>/dev/null && pwd -P) || {
    printf '[xiu3] 找不到宿主目录：%s\n' "$TARGET" >&2
    exit 1
}
case "$TARGET" in
    /|"$HOME"|"$HOME/"*)
        # The home directory itself is never a valid uninstall target.  A
        # child directory remains valid, including $HOME/xiu3.
        [ "$ACTION" != uninstall ] || [ "$TARGET" != "$HOME" ] || {
            printf '[xiu3] 拒绝卸载危险目录：%s\n' "$TARGET" >&2
            exit 1
        }
        ;;
esac

VENV=$(cd "$(dirname "$VENV")" 2>/dev/null && pwd -P)/$(basename "$VENV")
NB="$VENV/bin/nb"
VENV_PY="$VENV/bin/python"
STATE="$TARGET/.xiuxian3"
PID_FILE="$STATE/nb.pid"
LOG_FILE="$STATE/nb.log"
PAUSED_FILE="$STATE/nb.paused"
QQ_LOGIN="$STATE/qq_login.py"
mkdir -p "$STATE"

read_pid() {
    [ -s "$PID_FILE" ] || return 1
    local pid
    pid=$(tr -dc '0-9' < "$PID_FILE")
    [ -n "$pid" ] || return 1
    printf '%s\n' "$pid"
}

running_pid() {
    local pid
    pid=$(read_pid 2>/dev/null || true)
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    printf '%s\n' "$pid"
}

status() {
    local pid
    if pid=$(running_pid); then
        if [ -e "$PAUSED_FILE" ]; then
            printf '[xiu3] paused pid=%s\n' "$pid"
        else
            printf '[xiu3] running pid=%s\n' "$pid"
        fi
        printf '[xiu3] log=%s\n' "$LOG_FILE"
        return 0
    fi
    rm -f "$PID_FILE"
    rm -f "$PAUSED_FILE"
    printf '[xiu3] stopped\n'
    return 3
}

start() {
    if running_pid >/dev/null; then
        printf '[xiu3] 已经在运行：'
        running_pid
        return 0
    fi
    [ -x "$NB" ] || {
        printf '[xiu3] 找不到 nb：%s；请先执行 xiu3 update。\n' "$NB" >&2
        return 1
    }
    : > "$LOG_FILE"
    rm -f "$PAUSED_FILE"
    (
        cd "$TARGET"
        exec "$NB" run >>"$LOG_FILE" 2>&1
    ) &
    local pid=$!
    printf '%s\n' "$pid" > "$PID_FILE"
    sleep 1
    if running_pid >/dev/null; then
        printf '[xiu3] started pid=%s\n[xiu3] log=%s\n' "$pid" "$LOG_FILE"
    else
        printf '[xiu3] 启动失败，最后日志：\n'
        tail -n 30 "$LOG_FILE" 2>/dev/null || true
        rm -f "$PID_FILE"
        return 1
    fi
}

stop() {
    local pid
    pid=$(running_pid 2>/dev/null || true)
    [ -n "$pid" ] || { rm -f "$PID_FILE"; printf '[xiu3] 已停止\n'; return 0; }
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        printf '[xiu3] 正常停止超时，发送 KILL：%s\n' "$pid" >&2
        kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    rm -f "$PAUSED_FILE"
    printf '[xiu3] stopped\n'
}

pause_process() {
    local pid
    pid=$(running_pid 2>/dev/null || true)
    [ -n "$pid" ] || { printf '[xiu3] 当前未运行\n'; return 1; }
    kill -STOP "$pid"
    : > "$PAUSED_FILE"
    printf '[xiu3] paused pid=%s\n' "$pid"
}

resume_process() {
    local pid
    pid=$(read_pid 2>/dev/null || true)
    [ -n "$pid" ] && kill -CONT "$pid" 2>/dev/null || {
        printf '[xiu3] 当前没有可恢复的进程\n' >&2
        return 1
    }
    rm -f "$PAUSED_FILE"
    printf '[xiu3] resumed pid=%s\n' "$pid"
}

update() {
    if [ -n "$SOURCE_ROOT" ] && [ -x "$SOURCE_ROOT/scripts/install.sh" ]; then
        if { [ "$SOURCE_MODE" = release ] || { [ "$SOURCE_MODE" = auto ] && [ -f "$SOURCE_ROOT/.xiuxian3-release" ]; }; } && [ -x "$SOURCE_ROOT/scripts/onekey.sh" ]; then
            # Release installs refresh the immutable source cache from the
            # latest project.tar.gz before reinstalling the preserved host.
            local -a update_args=(update --target "$TARGET" --source "$SOURCE_ROOT" --source-mode release --mirror "$MIRROR" --venv "$VENV")
            [ -n "$MIRROR_URL" ] && update_args+=(--mirror-url "$MIRROR_URL")
            exec "$SOURCE_ROOT/scripts/onekey.sh" "${update_args[@]}"
        fi
        [[ "$SOURCE_MODE" == auto || "$SOURCE_MODE" == source ]] || {
            printf '[xiu3] 不支持的更新源码模式：%s\n' "$SOURCE_MODE" >&2
            return 2
        }
        if [ -d "$SOURCE_ROOT/.git" ]; then
            [ -z "$(git -C "$SOURCE_ROOT" status --porcelain)" ] || {
                printf '[xiu3] 源码目录有未提交改动，先提交或备份后再更新：%s\n' "$SOURCE_ROOT" >&2
                return 1
            }
            git -C "$SOURCE_ROOT" fetch --prune origin
            git -C "$SOURCE_ROOT" pull --ff-only origin main
        fi
        exec "$SOURCE_ROOT/scripts/install.sh" update --target "$TARGET" --source "$SOURCE_ROOT" \
            --source-mode source --mirror "$MIRROR" --venv "$VENV"
    fi
    printf '[xiu3] 未找到源码目录，尝试从 Python 包索引更新。\n'
    local python="$VENV/bin/python"
    local nb="$VENV/bin/nb"
    local group name
    for component in \
        'adapter|QQ' \
        'adapter|OneBot V11' \
        'driver|FastAPI' \
        'driver|HTTPX' \
        'driver|websockets' \
        'driver|AIOHTTP'; do
        IFS='|' read -r group name <<< "$component"
        "$nb" --cwd "$TARGET" --python "$python" "$group" update "$name"
    done
    "$python" -m pip install --upgrade --no-deps nonebot_plugin_xiuxian_3
}

uninstall() {
    local confirmed=0
    for arg in "$@"; do [ "$arg" = --yes ] && confirmed=1; done
    [ "$confirmed" = 1 ] || {
        printf '[xiu3] 卸载会删除宿主目录及其 SQLite 数据：%s\n' "$TARGET" >&2
        printf '[xiu3] 如已备份，请执行：xiu3 uninstall --yes\n' >&2
        return 2
    }
    stop || true
    case "$TARGET" in /|"$HOME") return 1 ;; esac
    for launcher in "$HOME/.local/bin/xiu3" "${PREFIX:-}/bin/xiu3"; do
        if [ -f "$launcher" ] && grep -Fq "$TARGET/.xiuxian3/control.sh" "$launcher" 2>/dev/null; then
            rm -f -- "$launcher"
        fi
    done
    rm -rf -- "$TARGET"
    printf '[xiu3] 已卸载宿主目录；共享虚拟环境未删除：%s\n' "$VENV"
}

case "$ACTION" in
    start) start ;;
    stop) stop ;;
    pause) pause_process ;;
    resume) resume_process ;;
    restart) stop; start ;;
    login)
        [ -x "$VENV_PY" ] || {
            printf '[xiu3] 找不到虚拟环境 Python：%s\n' "$VENV_PY" >&2
            exit 1
        }
        [ -f "$QQ_LOGIN" ] || {
            printf '[xiu3] 找不到 QQ 官方绑定 helper：%s；请先执行 xiu3 update。\n' "$QQ_LOGIN" >&2
            exit 1
        }
        was_running=0
        running_pid >/dev/null && was_running=1 || true
        if "$VENV_PY" "$QQ_LOGIN" --env "$TARGET/.env" "${LOGIN_ARGS[@]}"; then
            if ((was_running)); then
                printf '[xiu3] QQ 配置已更新，正在重启宿主。\n'
                stop
                start
            else
                printf '[xiu3] QQ 配置已更新；下次启动将使用新机器人。\n'
            fi
        else
            result=$?
            exit "$result"
        fi
        ;;
    status) status ;;
    logs)
        [ -f "$LOG_FILE" ] || { printf '[xiu3] 尚无运行日志：%s\n' "$LOG_FILE" >&2; exit 1; }
        tail -n "$LOG_LINES" "$LOG_FILE"
        ;;
    update) update ;;
    uninstall)
        if ((YES)); then uninstall --yes; else uninstall; fi
        ;;
    install)
        [ -n "$SOURCE_ROOT" ] && [ -x "$SOURCE_ROOT/scripts/onekey.sh" ] || {
            printf '[xiu3] install 需要安装源码；请从安装 checkout 运行 scripts/onekey.sh install。\n' >&2
            exit 2
        }
        exec "$SOURCE_ROOT/scripts/onekey.sh" install --target "$TARGET" --source "$SOURCE_ROOT" \
            --source-mode "$SOURCE_MODE" --mirror "$MIRROR" --venv "$VENV"
        ;;
    *)
        printf '用法：xiu3 {install|update|uninstall|start|stop|restart|status|logs|login}\n' >&2
        exit 2
        ;;
esac
