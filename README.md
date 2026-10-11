# NoneBot 修仙 3

本文及安装教程适用于仓库 `main` 分支；`main` 是公开安装、更新和使用入口。

`nonebot_plugin_xiuxian_3` 是一个面向 NoneBot 2 的文字修仙游戏插件。玩家从凡人开始，选择道途，修炼突破，探索三界，完成悬赏与主线，并把获得的材料用于生产、经济、灵兽和装备成长。角色进度保存在 SQLite，玩法内容由 `data/` 下的 JSON 内容包提供。

插件支持 OneBot V11 和 QQ 官方机器人。两个适配器共用同一套角色、任务和玩法服务；QQ 有 Markdown、蓝字和按键能力时使用增强消息，否则自动降级为可读文本。

## 玩法

- **启程与修炼**：`开始修仙`、寻仙问道、道号、道途、功法、修为、境界和突破。
- **世界与探索**：地点移动、采集、挖矿、历练、秘境、主线见闻和图鉴。
- **悬赏与战斗**：悬赏榜、目标进度、PvE、多人队伍和终局挑战。
- **生产与经济**：炼丹、炼器、布阵、灵田、设施、摆摊、求购和订单。
- **灵兽与装备**：灵兽、灵骑、喂养、运输、行囊、鞍具、装备和耐久。
- **任务与社交**：引路任务、日常、活动、宗门、师徒、道侣、队伍和切磋。

## 开始游戏

命令前缀由宿主的 `COMMAND_START` 决定，下面的示例不固定使用 `/`；QQ 群聊通常还需要 @机器人。

```text
开始修仙
修仙帮助
修仙帮助 启程
我的状态
```

帮助总览按六类组织：启程、修炼、探索、悬赏、生活、社交。分类帮助会给出下一步命令，QQ 可直接点击蓝字；OneBot 会收到同样内容的纯文本版本。

## 安装

安装器会创建 `$HOME/xiu3` 和 `$HOME/myenv`，检查 Python 3.11+、Git、curl、venv 与编译工具，安装 QQ、OneBot V11、FastAPI、HTTPX、websockets 和 AIOHTTP。

### Linux 一键安装

需要先安装 Git 和 curl（Debian/Ubuntu 可用 `sudo apt install git curl`）。

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/onekey.sh install --source-mode source --mirror direct
```

### GitHub Release 安装

版本化 Release 由 `main` 上的版本 tag 构建，资产名为 `project.tar.gz`。远程引导脚本从 `main` 获取；Release 模式要求对应的 GitHub Release 资产已经发布。

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh \
  | bash -s -- install --source-mode release --mirror accelerated
```

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

不要混用 Termux 与 `proot-distro` 的 Python/虚拟环境；在容器内请重新执行安装器。

### Windows

先确保 Git 可用；没有 Git 时在 PowerShell 执行 `winget install --id Git.Git --exact`，然后重开终端。

```powershell
git clone --branch main --single-branch https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
Set-Location xiuxian3-src
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\onekey_windows.ps1 install -SourceMode source -Mirror direct
```

### Docker

Docker 方式先取得 `main`，再使用仓库内的 `Dockerfile` 和 `docker-compose.yml`：

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
cp -n docker/env.example docker/.env
# 编辑 docker/.env 后执行
docker compose up -d --build
docker compose logs -f xiuxian3
```

`./data` 挂载内容和 SQLite，`./runtime` 挂载运行状态；凭据只写入 `docker/.env`，不要提交到 Git。

### 已有宿主手动安装

适合已经运行 NoneBot 的用户。先取得包含脚本的 checkout，再让安装器写入已有宿主；它只补缺失文件，不覆盖已有 `bot.py`、`pyproject.toml`、`.env` 或 `data/*.json`：

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git xiuxian3-src
cd xiuxian3-src
bash scripts/install.sh install /path/to/nonebot-host --venv /path/to/venv
```

已有宿主必须能被 `nb run` 启动，并允许安装 QQ/OneBot 适配器和所需驱动。需要修改插件源码时使用显式源码模式：

```bash
bash scripts/onekey.sh install --source-mode source --mirror direct \
  --target /path/to/nonebot-host --source "$PWD" --venv /path/to/venv
```

源码模式不会下载 Release。源码 checkout 应保持在 `main`；请先停止宿主并备份，再拉取更新：

```bash
/path/to/nonebot-host/xiu3 stop
cp -a /path/to/nonebot-host /path/to/nonebot-host.backup
git -C /path/to/xiuxian3-src pull --ff-only origin main
bash /path/to/xiuxian3-src/scripts/install.sh update /path/to/nonebot-host --venv /path/to/venv
/path/to/nonebot-host/xiu3 start
```

源码更新前应保存本地修改。Release 安装通过 `xiu3 update` 重新获取 `main` 版本 tag 对应的 Release 资产。

## 配置

宿主 `.env` 的最小配置：

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

直接在 `QQ_BOTS` 填写 QQ 开放平台提供的 AppID、Token、Secret 和事件意图，并完成开放平台权限配置；凭据只放在宿主 `.env`。群消息至少需要启用 `c2c_group_at_messages`。

```dotenv
QQ_BOTS='[{"id":"APP_ID","token":"APP_TOKEN","secret":"APP_SECRET","use_websocket":true,"intent":{"c2c_group_at_messages":true,"direct_message":true}}]'
```

`xiu3 login`（Windows 为 `& .\xiu3.ps1 login`）是可选的 QQ 官方 bot 绑定辅助，实际调用 QQ 的绑定页面和接口并更新 `.env`；它不是 OneBot/NapCat 的扫码登录，也不能替代手动维护 `QQ_BOTS` 凭据。Markdown 和自定义键盘需要对应的平台权限。

### OneBot V11

OneBot/NapCat 在自己的客户端中完成登录和扫码，NoneBot 只提供反向 WebSocket：

```text
ws://服务器地址:8080/onebot/v11/ws
```

NapCat/OneBot 与宿主两端使用同一个 `ONEBOT_V11_ACCESS_TOKEN`：

```dotenv
ONEBOT_V11_ACCESS_TOKEN=replace-with-your-random-token
```

Docker Compose 中宿主地址为 `ws://xiuxian3:8080/onebot/v11/ws`。只使用 OneBot 时保持 `QQ_BOTS=[]`；不要把 OneBot 登录信息写进 `QQ_BOTS`。

## 控制命令

Linux/Termux 安装后使用 `xiu3`，Windows 使用宿主目录中的 `xiu3.ps1`：

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

`uninstall --yes` 会删除宿主目录及其中的 SQLite 数据，不会删除共享虚拟环境；执行前请备份。

## 更新、备份与排错

Release 模式的 `xiu3 update` 重新获取 `project.tar.gz` 并安装依赖，保留宿主 `.env`、SQLite 数据、`data/`、`runtime/` 和用户自己的 JSON。更新前先停宿主，再备份；更新后重新启动：

```bash
xiu3 stop
cp -a "$HOME/xiu3" "$HOME/xiu3.backup"
xiu3 update
xiu3 start
```

启动失败先查看日志：

```bash
xiu3 status
tail -n 80 "$HOME/xiu3/.xiuxian3/nb.log"
```

常见原因是 Python/venv 版本不足、端口已占用、驱动未安装、QQ_BOTS 凭据或事件权限错误，以及 OneBot WebSocket 地址不匹配。代理下载失败可改用 `--mirror direct`；Release 不可用时请显式使用 `--source-mode source` 的 checkout。

## 文档与数据

- [玩家使用指南](docs/usage.md)
- [安装与更新](docs/installation.md)
- [发布与分发](docs/release-distribution.md)
- [开发与架构文档](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/index.md)
- [适配器说明](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/extensions/adapters/README.md)
- [运行与安全](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/operations.md)
- `data/`：JSON 内容定义；安装器只补宿主中缺失的内容文件
- 正常宿主的 PID 和运行日志：`.xiuxian3/nb.pid`、`.xiuxian3/nb.log`
- `runtime/`：Docker 额外挂载的运行状态目录
- [QQ 能力配置](https://github.com/liyw0205/nonebot_plugin_xiuxian_3/blob/main/docs/operations.md#1-配置层级)：`XIUXIAN3_QQ_CAPABILITIES` 控制 Markdown/键盘与纯文本降级

## 许可证

本项目采用 [MIT License](LICENSE)。
