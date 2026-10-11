# NoneBot 修仙 3

`nonebot_plugin_xiuxian_3` 是面向 NoneBot 2 的文字修仙游戏插件。玩家从凡人开始，选择道途，修炼突破，探索地点，完成采集、悬赏和战斗，再把所得材料用于生产、经济、装备与灵兽成长。角色进度保存在 SQLite，玩法内容位于宿主的 `data/` JSON 目录。

插件可接入 OneBot V11 和 QQ 官方机器人。两种适配器共用角色、任务和玩法服务；QQ 的 Markdown、蓝字和键盘是否呈现取决于账号能力与平台权限，未满足时保留可读文本。

## 玩法

- **启程与修炼**：创建角色、寻仙问道、道号、道途、功法、修为、境界和突破。
- **世界与探索**：移动、采集、挖矿、历练、秘境、主线见闻和图鉴。
- **悬赏与战斗**：悬赏榜、目标进度、自动 PvE、队伍战斗和终局挑战。
- **生产与经济**：炼丹、炼器、布阵、灵田、设施、摆摊、求购和订单。
- **灵兽与装备**：灵兽、灵骑、喂养、运输、行囊、鞍具、装备和耐久。
- **任务与社交**：引路任务、日常、活动、宗门、师徒、道侣、队伍和切磋。

## 开始游戏

命令前缀由宿主的 `COMMAND_START` 决定，下面示例省略前缀；QQ群聊通常还需要 @机器人。

```text
开始修仙
修仙帮助
修仙帮助 启程
我的状态
```

帮助总览按启程、修炼、探索、悬赏、生活、社交六类组织。QQ 可在有权限时点击蓝字，OneBot 会收到等价纯文本。

## 安装

安装器会创建 `$HOME/xiu3` 宿主和 `$HOME/myenv` 虚拟环境，安装 NoneBot CLI、QQ、OneBot V11 适配器及 FastAPI、HTTPX、websockets、AIOHTTP 驱动。源码安装会保留宿主已有的 `.env`、数据库和 JSON 文件。

### Linux 一键安装

先准备 Git 和 curl；Debian/Ubuntu 可执行 `sudo apt install git curl`。

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/onekey.sh install --source-mode source --mirror direct
```

安装完成后编辑 `$HOME/xiu3/.env`，再执行 `xiu3 start`。无法写入公共命令目录时，使用 `$HOME/xiu3/xiu3`。

### Termux

```bash
pkg update -y
pkg install -y git curl
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/onekey.sh install --source-mode source --mirror direct
termux-wake-lock
```

不要混用 Termux 与 `proot-distro` 的 Python/虚拟环境；在容器内重新执行安装器。

### Windows

先确保 Git 可用；没有 Git 时在 PowerShell 执行 `winget install --id Git.Git --exact`，然后重开终端。

```powershell
git clone --branch main --single-branch https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
Set-Location xiuxian3-src
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\onekey_windows.ps1 install -SourceMode source -Mirror direct
```

### Docker

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
cp -n docker/env.example docker/.env
# 编辑 docker/.env 后执行
docker compose up -d --build
docker compose logs -f xiuxian3
```

Docker 将 `./data` 挂载为内容和 SQLite 目录，将 `./runtime` 挂载为额外运行状态目录；凭据只写入 `docker/.env`。

### 已有 NoneBot 宿主

适合已经有 NoneBot 项目的用户。先获取 main 源码，再补齐宿主依赖；脚本不会覆盖已有 `bot.py`、`pyproject.toml`、`.env` 或 `data/*.json`。

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/install.sh install /path/to/nonebot-host --venv /path/to/venv
```

宿主需要能够使用 `nb run`，并允许安装 QQ/OneBot 适配器和驱动。源码开发时显式指定源码目录：

```bash
bash scripts/onekey.sh install --source-mode source --mirror direct \
  --target /path/to/nonebot-host --source "$PWD" --venv /path/to/venv
```

## 配置

宿主 `.env` 的最小示例：

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
# ONEBOT_V11_ACCESS_TOKEN=replace-with-your-random-token
```

### QQ 官方机器人

在 `QQ_BOTS` 填写 QQ 开放平台提供的 AppID、Token、Secret 和事件意图。群消息至少启用 `c2c_group_at_messages`，并按开放平台权限开通需要的事件。

```dotenv
QQ_BOTS='[{"id":"APP_ID","token":"APP_TOKEN","secret":"APP_SECRET","use_websocket":true,"intent":{"c2c_group_at_messages":true,"direct_message":true}}]'
```

`xiu3 login`（Windows 为 `& .\xiu3.ps1 login`）是 QQ 官方 bot 绑定辅助，调用 QQ 官方绑定接口并更新 `.env`；它不是 OneBot/NapCat 扫码登录，也不替代手填 `QQ_BOTS` 凭据。QQ Markdown、蓝字和键盘仍需要对应的平台能力与权限，真实呈现以账号和设备为准。

### OneBot V11 / NapCat

OneBot/NapCat 在自己的客户端完成登录和扫码，NoneBot 提供反向 WebSocket：

```text
ws://服务器地址:8080/onebot/v11/ws
```

宿主与 OneBot 两端使用同一个 `ONEBOT_V11_ACCESS_TOKEN`：

```dotenv
ONEBOT_V11_ACCESS_TOKEN=replace-with-your-random-token
```

Docker Compose 同一网络内使用 `ws://xiuxian3:8080/onebot/v11/ws`。只使用 OneBot 时保持 `QQ_BOTS=[]`，不要把 OneBot 登录信息写进 `QQ_BOTS`。

## 控制命令

Linux/Termux 使用 `xiu3`，Windows 使用宿主目录中的 `xiu3.ps1`：

```text
xiu3 start
xiu3 status
xiu3 pause
xiu3 resume
xiu3 restart
xiu3 stop
xiu3 update
xiu3 login
xiu3 uninstall --yes
```

`uninstall --yes` 会删除宿主目录及其中的 SQLite 数据，不会删除共享虚拟环境；执行前先备份。

## 更新、备份与排错

源码宿主的更新跟踪 `origin main`。先停止宿主，再备份，更新后重新启动：

```bash
xiu3 stop
cp -a "$HOME/xiu3" "$HOME/xiu3.backup"
xiu3 update
xiu3 start
```

`xiu3 update` 会在源码目录执行 `git fetch`、`git pull --ff-only origin main`，再运行安装脚本更新依赖和缺失内容；有未提交源码改动时会拒绝更新。不要在宿主运行时复制数据库。

查看状态和正常宿主日志：

```bash
xiu3 status
tail -n 80 "$HOME/xiu3/.xiuxian3/nb.log"
```

`.xiuxian3/nb.pid` 保存 PID，`.xiuxian3/nb.log` 保存 `nb run` 日志；`runtime/` 仅用于 Docker 额外挂载。端口冲突时修改宿主 `.env` 的 `PORT` 后重启。QQ 无消息先检查 `QQ_BOTS` 和事件权限，OneBot 无消息先检查反向 WebSocket 地址、令牌、防火墙和客户端连接日志。

## 文档与数据

- [玩家使用指南](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/usage.md)
- [安装与配置](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/installation.md)
- [文档总索引](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/index.md)
- [运行与安全](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/operations.md)
- [适配器说明](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/extensions/adapters/README.md)
- [QQ 能力配置](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/operations.md#1-配置层级)

`data/` 保存 JSON 内容定义和 SQLite 数据；普通宿主的运行 PID/日志位于 `.xiuxian3/`，Docker 另外挂载 `runtime/`。请勿把 token、Secret、数据库或备份提交到 Git。

## 许可证

本项目采用 [MIT License](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/LICENSE)。
