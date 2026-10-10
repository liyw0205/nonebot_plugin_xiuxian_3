# 安装、配置与更新

本文只描述当前仓库脚本实际支持的部署方式。要求 Python 3.11+；宿主由 NoneBot 的 `nb run` 启动，插件不单独监听业务端口。

## 一键安装

当前可用入口是 `work/m9-content-data` checkout 的源码模式；安装器默认创建 `$HOME/xiu3` 宿主和 `$HOME/myenv` 虚拟环境。

### Linux（当前推荐）

需要先安装 Git 和 curl（Debian/Ubuntu 可用 `sudo apt install git curl`）。

```bash
git clone --branch work/m9-content-data --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/onekey.sh install --source-mode source --mirror direct
```

### Release（发布后使用）

GitHub Release 发布 `project.tar.gz` 后，可通过同一分支的远程脚本安装。脚本优先尝试 Release 代理地址，失败后回退 GitHub 直连；当前 `latest` API 返回 404，因此当前部署不要复制此段。

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/work/m9-content-data/scripts/onekey.sh \
  | bash -s -- install --source-mode release --mirror accelerated
```

常用参数：

```bash
--target "$HOME/xiu3"                 # 宿主目录
--source "$HOME/.local/share/xiuxian3/source"  # Release 源码缓存
--venv "$HOME/myenv"                  # 虚拟环境
--mirror direct|accelerated|custom
--mirror-url URL
--index-url https://pypi.tuna.tsinghua.edu.cn/simple
--source-mode auto|release|source
```

发布资产存在后普通用户可选择 `release`；当前 checkout 使用 `source`。代理组由脚本维护，任何代理失败都会继续尝试并最终回退 GitHub 直连。不要把未验证的加速域名写入命令。

### Termux

```bash
pkg update -y
pkg install -y git curl
git clone --branch work/m9-content-data --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/onekey.sh install --source-mode source --mirror direct
termux-wake-lock
```

安装器会使用 `pkg` 补齐 Python、Git、curl 和 clang。使用 `proot-distro` 时在容器内单独创建虚拟环境，不要复用 Termux 的 venv。

### Windows

先确保 Git 可用；没有 Git 时在 PowerShell 执行 `winget install --id Git.Git --exact`，然后重开终端。

```powershell
git clone --branch work/m9-content-data --single-branch https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
Set-Location xiuxian3-src
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\onekey_windows.ps1 install -SourceMode source -Mirror direct
```

脚本会检查 Python 3.11+ 和 Git，缺少时尝试使用 `winget`；也可以先手动安装后再运行。

### Docker

先取得 `work/m9-content-data`，再使用仓库包含的 `Dockerfile`、`docker-compose.yml` 和 `docker/env.example`：

```bash
git clone --branch work/m9-content-data --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
cp -n docker/env.example docker/.env
# 编辑 docker/.env
docker compose up -d --build
docker compose logs -f xiuxian3
```

Compose 将宿主的 `./data` 挂载到容器 `/app/data`，将 `./runtime` 挂载到 `/app/runtime`。QQ 凭据只写入 `docker/.env`。

## 源码模式

源码模式必须显式使用 checkout，不会下载 Release：

```bash
git clone --branch work/m9-content-data --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/onekey.sh install --source-mode source --mirror direct
```

当前分支的源码更新不要使用 `xiu3 update`：控制脚本默认跟踪 `origin main`。请先备份并停止宿主，再明确拉取当前分支并重新安装：

```bash
/path/to/nonebot-host/xiu3 stop
cp -a /path/to/nonebot-host /path/to/nonebot-host.backup
git -C /path/to/xiuxian3-src pull --ff-only origin work/m9-content-data
bash /path/to/xiuxian3-src/scripts/install.sh update /path/to/nonebot-host --venv /path/to/venv
```

安装器要求 checkout 工作树干净；未提交修改不会被覆盖。Release 宿主才使用 `xiu3 update` 重新获取 Release 资产。

## 已有宿主手动安装

从包含脚本的 checkout 执行：

```bash
bash scripts/install.sh install /path/to/nonebot-host --venv /path/to/venv
```

该脚本会在指定 venv 中安装 `requirements.txt`、QQ/OneBot 适配器、FastAPI/HTTPX/websockets/AIOHTTP 和插件本身，并只复制宿主中缺失的 `bot.py`、`pyproject.toml`、`.env` 与 `data/*.json`。已有宿主的配置、代码和数据不会覆盖。宿主必须包含可由 `nb run` 加载的 `bot.py` 和 `pyproject.toml`。

如果只想手动执行步骤，顺序必须保持：创建 Python 3.11+ venv → `pip install -r requirements.txt` → `nb adapter install QQ` 与 `OneBot V11` → `nb driver install FastAPI HTTPX websockets AIOHTTP` → `pip install --no-deps /path/to/nonebot_plugin_xiuxian_3`。不要把插件安装到正在运行的另一套 venv。

## 最小配置

安装器复制的 `.env` 至少包含：

```dotenv
ENVIRONMENT=prod
DRIVER=~fastapi+~httpx+~websockets+~aiohttp
HOST=0.0.0.0
PORT=8080
LOG_LEVEL=INFO
COMMAND_START=["/"]
SUPERUSERS=[]
QQ_BOTS=[]
# XIUXIAN3_DATA_DIR=./data
```

### QQ 官方机器人

在 `QQ_BOTS` 中填写官方开放平台提供的 AppID、Token、Secret，并按 QQ 适配器要求配置事件意图与权限。群消息至少需要启用 `c2c_group_at_messages`；凭据只存于宿主 `.env`，不写入仓库。

```dotenv
QQ_BOTS='[{"id":"APP_ID","token":"APP_TOKEN","secret":"APP_SECRET","use_websocket":true,"intent":{"c2c_group_at_messages":true,"direct_message":true}}]'
```

OneBot 反向 WebSocket 两端使用同一个随机令牌：

```dotenv
ONEBOT_V11_ACCESS_TOKEN=请替换为随机令牌
```

`xiu3 login`（Windows 为 `& .\xiu3.ps1 login`）是可选的 QQ 官方 bot 绑定辅助，实际调用 `q.qq.com` 的绑定页面和接口并把结果安全写回 `.env`；它不是 OneBot/NapCat 扫码登录。真实官方账号权限和客户端显示仍需部署者验证。

### OneBot V11

OneBot/NapCat 在自身客户端完成账号登录和扫码，NoneBot 使用反向 WebSocket：

```text
ws://服务器地址:8080/onebot/v11/ws
```

只使用 OneBot 时保持 `QQ_BOTS=[]`。QQ 官方凭据与 OneBot 登录是两个独立入口。

## 控制、更新与备份

Linux/Termux：

```text
xiu3 start|stop|restart|status|pause|resume|update|login|uninstall --yes
```

Windows：

```powershell
& .\xiu3.ps1 start
& .\xiu3.ps1 status
& .\xiu3.ps1 update
& .\xiu3.ps1 uninstall --yes
```

Release 宿主的 `update` 会重新获取 `project.tar.gz`，保留宿主 `.env`、SQLite、`data/`、`runtime/` 和用户 JSON。当前源码 checkout 不要使用 `xiu3 update`，请按上文明确拉取 `work/m9-content-data` 后执行 `scripts/install.sh update`。停止宿主后再备份，更新完成后重新启动：

```bash
xiu3 stop
cp -a "$HOME/xiu3" "$HOME/xiu3.backup"
xiu3 update
xiu3 start
```

正常宿主的 PID 和日志在 `.xiuxian3/nb.pid`、`.xiuxian3/nb.log`；`runtime/` 是 Docker 额外挂载的运行状态目录。QQ Markdown/键盘能力由 [`XIUXIAN3_QQ_CAPABILITIES`](operations.md#1-配置层级) 控制；未配置时沿用默认能力，配置存在但未列当前 AppID 时仅发送文本。

## 排错

查看控制状态和日志：

```bash
xiu3 status
tail -n 80 "$HOME/xiu3/.xiuxian3/nb.log"
```

- Python 版本或 venv 不可用：安装 Python 3.11+ 及 venv 模块。
- 端口冲突：修改宿主 `.env` 的 `PORT` 后重启。
- 适配器/驱动缺失：在同一 venv 重新运行 `scripts/install.sh update`；Release 宿主可使用 `xiu3 update`。
- QQ 无消息：检查 `QQ_BOTS`、开放平台事件权限和 QQ 适配器版本。
- OneBot 无消息：检查 NapCat 的反向 WebSocket URL、端口、防火墙和连接日志。
- Release 下载失败：先重试，再使用 `--mirror direct`；需要源码时显式使用 `--source-mode source`。

完整玩法入口和数据目录见 [文档索引](index.md)；发布资产规则见 [发布分发](release-distribution.md)。
