#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

REPOSITORY="https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
RELEASE_ARCHIVE="https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
RELEASE_MIRRORS=(
    "https://gh-proxy.com/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
    "https://ghfast.top/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
    "https://ghproxy.vip/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
    "https://gh-proxy.org/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
)
ACCELERATED_REPOSITORIES=(
    "https://gh-proxy.com/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
    "https://ghfast.top/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
    "https://ghproxy.vip/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
    "https://gh-proxy.org/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
)
ACCELERATED_PROBES=(
    "https://gh-proxy.com/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
    "https://ghfast.top/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
    "https://ghproxy.vip/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
    "https://gh-proxy.org/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
)
TUNA_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
ACTION=install
TARGET="$HOME/xiu3"
SOURCE="${XIUXIAN3_SOURCE_DIR:-$HOME/.local/share/xiuxian3/source}"
VENV="${VENV_PATH:-$HOME/myenv}"
MIRROR=""
MIRROR_URL=""
SOURCE_MODE="${XIUXIAN3_SOURCE_MODE:-auto}"
INDEX_URL="${PIP_INDEX_URL:-$TUNA_INDEX}"
YES=0
LOG_LINES=80
LOGIN_ARGS=()

log() { printf '[xiuxian3] %s\n' "$*"; }
fail() { printf '[xiuxian3] 错误：%s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
用法：onekey.sh <install|update|uninstall|start|stop|restart|status|logs|login> [选项]

选项：
  --target PATH       宿主目录（默认 $HOME/xiu3）
  --source PATH       插件源码目录（默认 $HOME/.local/share/xiuxian3/source）
  --venv PATH         Python 虚拟环境（默认 $HOME/myenv）
  --mirror MODE       direct、accelerated 或 custom
  --mirror-url URL    自定义 Release 归档 URL（source 模式为 Git 地址）
  --source-mode MODE  auto、release 或 source；默认本地源码、远程 Release
  --lines N           logs 显示最近 N 行（默认 80）
  --index-url URL     pip 镜像（默认清华源）
  --yes               确认卸载宿主目录及其中的数据
  -h, --help          显示帮助

首次安装会补齐系统 Python、Git 和 curl，再下载源码并安装独立 NoneBot 宿主。
EOF
}

if (($#)) && [[ "$1" =~ ^(install|update|uninstall|start|stop|restart|status|logs|login)$ ]]; then
    ACTION=$1
    shift
fi

while (($#)); do
    case "$1" in
        --target|--source|--venv|--mirror|--mirror-url|--index-url|--source-mode|--lines)
            (($# >= 2)) || fail "$1 需要一个值"
            key=$1
            value=$2
            case "$key" in
                --target) TARGET=$value ;;
                --source) SOURCE=$value ;;
                --venv) VENV=$value ;;
                --mirror) MIRROR=$value ;;
                --mirror-url) MIRROR_URL=$value ;;
                --index-url) INDEX_URL=$value ;;
                --source-mode) SOURCE_MODE=$value ;;
                --lines) LOG_LINES=$value ;;
            esac
            shift 2
            ;;
        --yes) YES=1; shift ;;
        --timeout|--interval)
            (($# >= 2)) || fail "$1 需要一个值"
            LOGIN_ARGS+=("$1" "$2")
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        -*) fail "未知选项：$1" ;;
        *)
            [ "$TARGET" = "$HOME/xiu3" ] || fail "只能指定一个宿主目录"
            TARGET=$1
            shift
            ;;
    esac
done

[[ "$LOG_LINES" =~ ^[1-9][0-9]*$ ]] || fail "--lines 必须是正整数"

TARGET="$(mkdir -p "$(dirname "$TARGET")" && cd "$(dirname "$TARGET")" && pwd -P)/$(basename "$TARGET")"
SOURCE="$(mkdir -p "$(dirname "$SOURCE")" && cd "$(dirname "$SOURCE")" && pwd -P)/$(basename "$SOURCE")"

if [ "$ACTION" = uninstall ]; then
    [ "$YES" = 1 ] || fail "卸载会删除宿主目录和 SQLite 数据；确认备份后添加 --yes。"
    [ -x "$TARGET/xiu3" ] || fail "没有找到控制命令：$TARGET/xiu3"
    exec "$TARGET/xiu3" uninstall --yes
fi
if [[ "$ACTION" =~ ^(start|stop|restart|status|logs|login)$ ]]; then
    [ -x "$TARGET/xiu3" ] || fail "没有找到宿主管理命令：$TARGET/xiu3；请先执行 install。"
    control_args=("$ACTION" --target "$TARGET" --source "$SOURCE" --source-mode "$SOURCE_MODE" --mirror "$MIRROR" --venv "$VENV")
    [ -n "$MIRROR_URL" ] && control_args+=(--mirror-url "$MIRROR_URL")
    [ "$ACTION" != logs ] || control_args+=(--lines "$LOG_LINES")
    [ "$YES" = 0 ] || control_args+=(--yes)
    control_args+=("${LOGIN_ARGS[@]}")
    exec "$TARGET/xiu3" "${control_args[@]}"
fi
if [ "$ACTION" = update ] && [ ! -d "$TARGET" ]; then
    fail "更新目标不存在：$TARGET；请先执行 install。"
fi

version_at_least_311() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

find_python() {
    local candidate
    for candidate in "${PYTHON_BIN:-}" python3.13 python3.12 python3.11 python3 python; do
        [ -n "$candidate" ] || continue
        if command -v "$candidate" >/dev/null 2>&1 && version_at_least_311 "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

run_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        fail "安装系统依赖需要 root 权限或 sudo：$*"
    fi
}

install_system_tools() {
    local python_ok=0 venv_ok=0 git_ok=0 curl_ok=0 compiler_ok=1 python_command=""
    python_command=$(find_python 2>/dev/null || true)
    if [ -n "$python_command" ]; then
        python_ok=1
        "$python_command" -m venv --help >/dev/null 2>&1 && venv_ok=1 || true
    fi
    command -v git >/dev/null 2>&1 && git_ok=1 || true
    command -v curl >/dev/null 2>&1 && curl_ok=1 || true
    if [ -n "${PREFIX:-}" ] && [ -x "${PREFIX}/bin/pkg" ]; then
        command -v clang >/dev/null 2>&1 && compiler_ok=1 || compiler_ok=0
    else
        { command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1; } || compiler_ok=0
    fi
    if ((python_ok && venv_ok && git_ok && curl_ok && compiler_ok)); then return; fi

    if [ -n "${PREFIX:-}" ] && [ -x "${PREFIX}/bin/pkg" ]; then
        log "通过 Termux pkg 安装缺失的系统命令"
        pkg update -y
        pkg install -y python git curl clang
    elif command -v apt-get >/dev/null 2>&1; then
        log "通过 apt 安装 Python、venv、Git、curl 和构建工具"
        run_as_root apt-get update
        apt_packages=(python3 python3-venv python3-pip python3-dev build-essential git curl ca-certificates)
        if ! find_python >/dev/null 2>&1 && \
            apt-cache show python3.11 >/dev/null 2>&1 && \
            apt-cache show python3.11-venv >/dev/null 2>&1 && \
            apt-cache show python3.11-dev >/dev/null 2>&1; then
            apt_packages+=(python3.11 python3.11-venv python3.11-dev)
        fi
        run_as_root apt-get install -y "${apt_packages[@]}"
    elif command -v dnf >/dev/null 2>&1; then
        log "通过 dnf 安装 Python、Git、curl 和构建工具"
        run_as_root dnf install -y python3 python3-pip python3-devel gcc gcc-c++ git curl ca-certificates
    elif command -v yum >/dev/null 2>&1; then
        log "通过 yum 安装 Python、Git、curl 和构建工具"
        run_as_root yum install -y python3 python3-pip python3-devel gcc gcc-c++ git curl ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        log "通过 pacman 安装 Python、Git、curl 和构建工具"
        run_as_root pacman -Sy --needed --noconfirm python base-devel git curl ca-certificates
    elif command -v apk >/dev/null 2>&1; then
        log "通过 apk 安装 Python、venv、Git、curl 和构建工具"
        run_as_root apk add python3 py3-pip py3-virtualenv python3-dev build-base git curl ca-certificates bash
    else
        fail "无法识别系统包管理器。请安装 Python 3.11+、Git、curl 和 venv 后重试。"
    fi

    python_command=$(find_python) || fail "系统包已处理，但未找到 Python 3.11+；请升级 Python 后重试。"
    "$python_command" -m venv --help >/dev/null 2>&1 || fail "系统 Python 缺少 venv 模块；请安装对应的 venv 包后重试。"
    command -v git >/dev/null 2>&1 || fail "Git 安装后仍不可用，请检查系统 PATH。"
    command -v curl >/dev/null 2>&1 || fail "curl 安装后仍不可用，请检查系统 PATH。"
    if [ -n "${PREFIX:-}" ] && [ -x "${PREFIX}/bin/pkg" ]; then
        command -v clang >/dev/null 2>&1 || fail "clang 安装后仍不可用，请检查 Termux 包环境。"
    else
        { command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1; } || fail "C 编译器安装后仍不可用，请检查系统构建工具。"
    fi
}

choose_mirror() {
    [ -n "$MIRROR" ] && return
    if [ -r /dev/tty ]; then
        printf '选择仓库下载方式：\n  1) GitHub 直连\n  2) 代理组测速并选最低延迟\n  3) 自定义 Git 地址\n请选择 [1]: ' > /dev/tty
        local choice
        read -r choice < /dev/tty || choice=1
        case "$choice" in
            2) MIRROR=accelerated ;;
            3)
                MIRROR=custom
                printf '输入完整 Git 克隆地址：' > /dev/tty
                read -r MIRROR_URL < /dev/tty || MIRROR_URL=
                [ -n "$MIRROR_URL" ] || fail "自定义 Git 地址不能为空"
                ;;
            *) MIRROR=direct ;;
        esac
    else
        MIRROR=direct
    fi
}

select_fastest_proxy() {
    local best_url="" best_latency="" result status latency index proxy
    for index in "${!ACCELERATED_REPOSITORIES[@]}"; do
        result=$(curl --location --silent --show-error --connect-timeout 4 --max-time 10 \
            --output /dev/null --write-out '%{http_code} %{time_starttransfer}' \
            "${ACCELERATED_PROBES[$index]}" 2>/dev/null || true)
        IFS=' ' read -r status latency <<< "$result" || true
        proxy=${ACCELERATED_REPOSITORIES[$index]#https://}
        proxy=${proxy%%/*}
        if [ "$status" != 200 ] || ! [[ "$latency" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
            log "代理测速失败：$proxy" >&2
            continue
        fi
        log "代理测速：$proxy ${latency}s" >&2
        if [ -z "$best_latency" ] || awk -v current="$latency" -v best="$best_latency" 'BEGIN { exit !(current < best) }'; then
            best_latency=$latency
            best_url=${ACCELERATED_REPOSITORIES[$index]}
        fi
    done
    if [ -z "$best_url" ]; then
        log "代理组均不可用，改用 GitHub 直连" >&2
        best_url=$REPOSITORY
    else
        log "选择代理延迟最低的仓库源：$best_url" >&2
    fi
    printf '%s\n' "$best_url"
}

release_urls() {
    case "$MIRROR" in
        direct) printf '%s\n' "$RELEASE_ARCHIVE" ;;
        accelerated|"") printf '%s\n' "${RELEASE_MIRRORS[@]}"; printf '%s\n' "$RELEASE_ARCHIVE" ;;
        custom) [ -n "$MIRROR_URL" ] || fail "custom 模式需要 --mirror-url"; printf '%s\n' "$MIRROR_URL" ;;
        *) fail "不支持的仓库下载方式：$MIRROR" ;;
    esac
}

download_release_source() {
    local work archive extract root url
    work=$(mktemp -d "${TMPDIR:-/tmp}/xiuxian3-release.XXXXXX")
    archive="$work/project.tar.gz"
    extract="$work/extract"
    mkdir -p "$extract"
    while IFS= read -r url; do
        log "下载 Release 资产：$url"
        if ! curl --fail --location --retry 2 --connect-timeout 8 --max-time 180 \
            --proto '=https' --proto-redir '=https' "$url" -o "$archive"; then
            log "下载失败，尝试下一个地址" >&2
            continue
        fi
        rm -rf "$extract"
        mkdir -p "$extract"
        if ! tar -xzf "$archive" -C "$extract" 2>/dev/null; then
            log "资产不是有效的 project.tar.gz，尝试下一个地址" >&2
            continue
        fi
        root=$(find "$extract" -mindepth 1 -maxdepth 3 -type f -name pyproject.toml -print -quit)
        [ -n "$root" ] || { log "资产缺少 pyproject.toml，尝试下一个地址" >&2; continue; }
        root=${root%/pyproject.toml}
        if [ -e "$SOURCE" ] && [ ! -f "$SOURCE/.xiuxian3-release" ]; then
            rm -rf "$work"
            fail "源码目录已存在且不是 Release 管理目录：$SOURCE；如需开发源码请使用 --source-mode source"
        fi
        rm -rf "$SOURCE"
        mkdir -p "$SOURCE"
        cp -R "$root"/. "$SOURCE"/
        printf '%s\n' "$url" > "$SOURCE/.xiuxian3-release"
        log "已准备 Release 源码：$SOURCE"
        rm -rf "$work"
        return 0
    done < <(release_urls)
    rm -rf "$work"
    fail "无法获取有效的 project.tar.gz；代理失败后直连也不可用，请稍后重试或使用 --source-mode source。"
}

ensure_git_source() {
    if [ -d "$SOURCE/.git" ]; then
        if [ "$ACTION" = update ]; then
            [ -z "$(git -C "$SOURCE" status --porcelain)" ] || fail "源码目录有未提交改动：$SOURCE"
            log "更新开发源码：$SOURCE"
            git -C "$SOURCE" fetch --prune origin
            git -C "$SOURCE" pull --ff-only origin main
        fi
        return
    fi
    [ ! -e "$SOURCE" ] || fail "源码路径已存在但不是 Git 仓库：$SOURCE"

    choose_mirror
    local url=$REPOSITORY
    case "$MIRROR" in
        direct) url=$REPOSITORY ;;
        accelerated) url=$(select_fastest_proxy) ;;
        custom) url=$MIRROR_URL; [ -n "$url" ] || fail "custom 模式需要 --mirror-url" ;;
        *) fail "不支持的仓库下载方式：$MIRROR" ;;
    esac
    mkdir -p "$(dirname "$SOURCE")"
    log "从 $url 获取开发源码"
    if ! git clone --depth 1 --branch main "$url" "$SOURCE"; then
        if [ "$MIRROR" = accelerated ] && [ "$url" != "$REPOSITORY" ]; then
            rm -rf "$SOURCE"
            for fallback_url in "${ACCELERATED_REPOSITORIES[@]}"; do
                [ "$fallback_url" != "$url" ] || continue
                log "代理克隆失败，尝试下一个地址：$fallback_url"
                if git clone --depth 1 --branch main "$fallback_url" "$SOURCE"; then
                    url=$fallback_url
                    break
                fi
                rm -rf "$SOURCE"
            done
            if [ ! -d "$SOURCE/.git" ]; then
                log "代理组克隆失败，尝试 GitHub 直连"
                git clone --depth 1 --branch main "$REPOSITORY" "$SOURCE" \
                    || fail "直连也失败；可重试并指定 --mirror-url 自建 Git 镜像。"
            fi
        else
            fail "仓库下载失败；可更换 --mirror accelerated 或 --mirror-url。"
        fi
    fi
}

ensure_source() {
    local script_path=${BASH_SOURCE[0]}
    local local_root=""
    if [[ "$script_path" != /dev/* && -f "$script_path" ]]; then
        local_root="$(cd "$(dirname "$script_path")/.." && pwd -P)"
        [ -f "$local_root/pyproject.toml" ] || local_root=""
    fi
    case "$SOURCE_MODE" in auto|source|release) ;;
        *) fail "不支持的源码模式：$SOURCE_MODE（可选 auto、release、source）" ;;
    esac
    if [ "$SOURCE_MODE" != release ] && [ -n "$local_root" ]; then
        SOURCE=$local_root
        return
    fi

    if [ "$SOURCE_MODE" = source ]; then
        ensure_git_source
        return
    fi
    mkdir -p "$(dirname "$SOURCE")"
    download_release_source
}

install_system_tools
ensure_source
[ -x "$SOURCE/scripts/install.sh" ] || fail "源码目录缺少 scripts/install.sh：$SOURCE"

args=("$SOURCE/scripts/install.sh" "$ACTION" --target "$TARGET" --source "$SOURCE" \
    --source-mode "$SOURCE_MODE" --mirror "$MIRROR" --venv "$VENV" --index-url "$INDEX_URL")
[ -n "$MIRROR_URL" ] && args+=(--mirror-url "$MIRROR_URL")
[ "$YES" = 0 ] || args+=(--yes)
exec bash "${args[@]}"
