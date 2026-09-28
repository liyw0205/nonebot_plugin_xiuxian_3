# NoneBot 修仙 3

`nonebot_plugin_xiuxian_3` 是 NoneBot 2 修仙文字游戏插件。玩家通过聊天命令创建角色、修炼、探索、战斗和参与多人玩法；角色数据保存在 SQLite，境界、物品、任务、敌人和配方等内容由 JSON 提供。

插件需要独立的 NoneBot 宿主项目运行，不是其他插件的子插件，也不能直接把插件模块当作机器人服务启动。仓库提供宿主模板和安装脚本；安装后使用真实的 `nb run` 启动。

## 适配器

- QQ 官方适配器支持文本、Markdown、蓝字命令链接及按键。
- OneBot V11 使用纯文本或合并转发，不发送 Markdown 标记、蓝字或按键。
- 两种适配器共用游戏数据和命令逻辑；可以在同一个宿主中注册。

## 安装

需要 Python 3.11 或更高版本。以下一键安装命令均在**本仓库根目录**执行，默认创建独立宿主 `$HOME/nonebot-bot` 和虚拟环境 `$HOME/myenv`；已存在的宿主配置和内容文件不会被覆盖。首次启动前请按下文配置宿主 `.env`。

### Linux

```bash
bash scripts/install.sh install "$HOME/nonebot-bot"
cd "$HOME/nonebot-bot"
# 按需配置 .env 后启动
xiu3 start
```

如果 `xiu3` 不在 `PATH` 中，可在宿主目录执行 `./xiu3 start`。重新运行 `install` 可补齐缺少的文件；更新使用 `xiu3 update`。

### Windows

在 PowerShell 中从仓库根目录执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& .\scripts\install_windows.ps1 install "$HOME\nonebot-bot"
Set-Location "$HOME\nonebot-bot"
# 按需配置 .env 后启动
& .\xiu3.ps1 start
```

也可在命令提示符使用 `scripts\install_windows.bat install %USERPROFILE%\nonebot-bot`。Windows 控制命令为宿主目录中的 `xiu3.ps1` 或 `xiu3.cmd`。

### Termux

在 Termux 中从仓库根目录执行：

```bash
pkg update
pkg install -y python git clang
bash scripts/install_termux.sh install "$HOME/nonebot-bot"
cd "$HOME/nonebot-bot"
# 按需配置 .env 后启动
xiu3 start
```

原生 Termux 使用自身的 Python 虚拟环境；`proot-distro` 内应按 Linux 步骤另建虚拟环境，不能混用。

### Docker

在仓库根目录执行：

```bash
cp -n docker/env.example docker/.env
# 填写 docker/.env 中实际需要的机器人配置
docker compose build
docker compose up -d
docker compose logs -f
```

容器同样运行 `nb run`。`./data` 挂载至容器 `/app/data`，`./runtime` 挂载至 `/app/runtime`；不要把机器人令牌或数据库提交到 Git。

### 手动安装

不使用安装脚本时，新建独立宿主的 Linux 示例：

```bash
python3 -m venv "$HOME/myenv"
"$HOME/myenv/bin/python" -m pip install '.[nonebot,onebot,qq]'
mkdir -p "$HOME/nonebot-bot"
cp examples/nonebot/bot.py examples/nonebot/pyproject.toml "$HOME/nonebot-bot/"
cp examples/nonebot/.env.example "$HOME/nonebot-bot/.env"
cd "$HOME/nonebot-bot"
"$HOME/myenv/bin/nb" run
```

上例中的安装和复制命令需在仓库根目录运行；已有宿主应只安装插件，并在其 `bot.py` 注册所需适配器、在 `pyproject.toml` 的 `[tool.nonebot.plugins]` 中加载 `nonebot_plugin_xiuxian_3`，不要覆盖原有文件。Windows 和 Termux 的手动安装步骤见[完整安装文档](docs/installation.md)。手动安装不生成 `xiu3` 控制命令。

## 配置与启动

安装器从 `examples/nonebot/.env.example` 创建宿主 `.env`，请在宿主中配置监听地址和实际使用的适配器：

```dotenv
DRIVER=~fastapi+~httpx+~websockets+~aiohttp
HOST=0.0.0.0
PORT=8080
QQ_BOTS=[]
XIUXIAN3_DATA_DIR=./data
```

QQ 机器人需要按 QQ 适配器要求填写 `QQ_BOTS`。OneBot V11 通过 `nb run` 启动的宿主监听入口连接，使用 `HOST` / `PORT`，无需配置额外的 `ONEBOT_V11_WS_URLS`。不设置 `XIUXIAN3_DATA_DIR` 时默认使用宿主的 `./data`。宿主模板 `bot.py` 已注册 QQ 和 OneBot V11 适配器，`pyproject.toml` 已声明本插件。

一键安装后的日常控制命令：

```bash
xiu3 start
xiu3 status
xiu3 pause
xiu3 resume
xiu3 stop
xiu3 restart
xiu3 update
```

Windows 在宿主目录用 `.\xiu3.ps1` 替换 `xiu3`。`xiu3 uninstall --yes` 会删除宿主目录及其中的 SQLite 数据；请先备份，不会删除共享的 `$HOME/myenv`。手动安装时在宿主目录执行对应虚拟环境的 `nb run`。

## 数据与文档

插件内置只读 JSON 内容包；安装脚本和 Docker 会将可编辑的 JSON 复制到宿主数据目录，已有内容不会被覆盖。SQLite 和备份位于所配置的数据目录，`xiu3` 的运行日志位于宿主 `.xiuxian3/`；升级前应自行备份。

- [完整安装文档](docs/installation.md)：各平台一键安装、手动安装和排障。

仅需检查已安装插件的内容和 SQLite 时可执行 `"$HOME/myenv/bin/python" -m nonebot_plugin_xiuxian_3 --data-dir ./data`；这不是 NoneBot 的启动命令。
