# NoneBot 修仙 3

`nonebot_plugin_xiuxian_3` 是 NoneBot 2 聊天游戏插件。玩家可创建角色、修炼、探索、战斗和参与多人玩法；SQLite 保存角色进度，JSON 内容包提供境界、物品、任务、敌人和配方。

插件运行在独立的 NoneBot 宿主项目中，不是其他插件的子插件。仓库提供一键安装器、宿主模板和 Docker 配置，宿主由 `nb run` 启动。

## 适配器

- QQ 官方适配器支持 Markdown、蓝字命令链接和按键。
- OneBot V11 使用纯文本或合并转发，不发送 Markdown 标记、蓝字或按键。
- 两种适配器共用角色数据和命令逻辑，可在同一个宿主中注册。

## 一键安装

安装器会检查并安装系统 Python、Git 等依赖，创建 `$HOME/myenv`，使用清华 pip 源安装 `nb-cli==1.5.0`，再通过 `nb adapter install` 和 `nb driver install` 安装适配器、驱动，最后创建独立宿主 `$HOME/xiu3` 并安装插件。仓库下载方式可交互选择直连、代理测速选优或自定义 Git 地址；已有宿主配置和 JSON 内容不会被覆盖。

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

如果 GitHub 访问较慢，可改用代理获取引导脚本，并在提示中选择加速源：

```bash
curl -fsSL https://gh-proxy.com/https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

引导脚本也可从 `ghproxy.net`、`ghfast.top`、`ghproxy.vip` 或 `gh-proxy.org` 获取。脚本下载后会测速完整代理组并选择延迟最低的可用仓库源。

也可以直接指定仓库源，跳过选择菜单：

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install --mirror accelerated
```

系统包安装需要 root 或 `sudo`。选择代理加速时，安装器会测速 `gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`ghproxy.vip` 和 `gh-proxy.org` 的 Git refs 响应，选用延迟最低的可用地址；克隆失败会尝试组内其他地址，代理均不可用时回退直连。安装后编辑 `$HOME/xiu3/.env`，然后启动：

```bash
cd "$HOME/xiu3"
xiu3 start
```

### Windows

在 PowerShell 中下载并运行引导脚本。脚本可通过 `winget` 安装 Python 3.12 和 Git，并提供直连、加速源、自定义地址选择：

```powershell
$installer = Join-Path $env:TEMP 'xiuxian3-onekey.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey_windows.ps1' -OutFile $installer
powershell -NoProfile -ExecutionPolicy Bypass -File $installer install
```

如果 GitHub 访问较慢，可将下载 URL 中的代理换成 `gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`ghproxy.vip` 或 `gh-proxy.org`。安装完成后在 PowerShell 中运行：

```powershell
Set-Location "$HOME\xiu3"
& .\xiu3.ps1 start
```

`winget` 不可用时，请先安装 Python 3.11+、Git 和 Windows App Installer，再重新运行脚本。

### Termux

在 Termux 中执行：

```bash
pkg update -y
pkg install -y curl
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

安装器会使用 `pkg` 补齐 Python、Git、curl 和编译工具。启动前建议执行 `termux-wake-lock`，再运行 `xiu3 start`。`proot-distro` 环境请在 Linux 容器内单独安装，不要混用 Termux 和容器的 Python。

### 更新与卸载

日常控制由安装器生成的 `xiu3` 命令完成：

```bash
xiu3 status
xiu3 pause
xiu3 resume
xiu3 restart
xiu3 update
xiu3 stop
xiu3 login
```

首次更新会同步插件仓库并更新虚拟环境依赖。Windows 使用宿主目录中的 `xiu3.ps1`。卸载会删除宿主目录和其中的 SQLite 数据，需显式确认：

```bash
xiu3 uninstall --yes
```

共享虚拟环境 `$HOME/myenv` 和插件源码缓存不会随宿主卸载。

## Docker

在仓库目录中配置环境并启动：

```bash
cp -n docker/env.example docker/.env
# 编辑 docker/.env，填入实际机器人配置
docker compose build
docker compose up -d
docker compose logs -f
```

容器使用 `nb run` 启动；`./data` 保存 JSON 内容和 SQLite 数据，`./runtime` 保存运行状态。不要将机器人令牌或数据库提交到 Git。

## 手动安装

手动安装需要先取得仓库源码。Linux 示例：

```bash
git clone https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git
cd nonebot_plugin_xiuxian_3
python3 -m venv "$HOME/myenv"
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
"$HOME/myenv/bin/python" -m pip config --site set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
"$HOME/myenv/bin/python" -m pip install -r requirements.txt
mkdir -p "$HOME/xiu3"
cp examples/nonebot/bot.py examples/nonebot/pyproject.toml "$HOME/xiu3/"
cp examples/nonebot/.env.example "$HOME/xiu3/.env"
cp -R data "$HOME/xiu3/"
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" adapter install --no-restrict-version QQ
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" adapter install --no-restrict-version "OneBot V11"
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install FastAPI
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install HTTPX
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install websockets
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install AIOHTTP
"$HOME/myenv/bin/python" -m pip install --no-deps .
cd "$HOME/xiu3"
"$HOME/myenv/bin/nb" run
```

如果只想装入已有的 NoneBot 宿主，请按[完整安装文档](docs/installation.md)注册适配器并加载插件。手动安装不会生成 `xiu3` 控制命令。

## 配置与连接

安装后先编辑宿主目录的 `.env`。下面是基础配置，`HOST` 是 NoneBot 的监听地址，`PORT` 是监听端口：

```dotenv
ENVIRONMENT=prod
DRIVER=~fastapi+~httpx+~websockets+~aiohttp
HOST=0.0.0.0
PORT=8080
LOG_LEVEL=INFO
COMMAND_START=["/"]
SUPERUSERS=[]
QQ_BOTS=[]
XIUXIAN3_DATA_DIR=./data
# ONEBOT_V11_ACCESS_TOKEN=替换为随机令牌
```

同一台机器上的 NapCat 可以将 `HOST` 设为 `127.0.0.1`；NapCat 在其他机器或容器时，设为 `0.0.0.0`，并在防火墙中只允许 NapCat 所在网络访问 `PORT`。客户端填写实际可访问的服务器 IP 或域名，不能填写 `0.0.0.0`。

### OneBot V11 / NapCat

OneBot V11 使用反向 WebSocket：启动 NoneBot 后，NapCat 主动连接到它。NapCat 的网络配置中添加 **WebSocket 客户端**，地址填写：

```text
ws://服务器地址:8080/onebot/v11/ws
```

NapCat 和 NoneBot 在同一台机器时，地址可用 `ws://127.0.0.1:8080/onebot/v11/ws`；NapCat 在 Docker Compose 同一网络时，可用 `ws://xiuxian3:8080/onebot/v11/ws`；其他机器则填写 NoneBot 服务器的 LAN IP 或域名。跨主机连接建议配置强随机 `ONEBOT_V11_ACCESS_TOKEN`，并用防火墙限制来源；NapCat 的 WebSocket 客户端也必须填写相同的 Access Token。这个连接方式不需要在插件 `.env` 中填写 WebSocket 目标地址。

启动后可在 NapCat 连接日志中确认 WebSocket 已连接，再发送 `/开始修仙` 或 `/我的状态` 测试。使用 Docker 时，Compose 默认将宿主机 `8080` 映射到容器 `8080`；NapCat 在 Compose 外部时连接宿主机 IP，在同一 Compose 网络时使用服务名 `xiuxian3`。

### QQ 官方机器人

QQ 官方适配器默认使用 WebSocket，由 NoneBot 主动连接 QQ；通常不需要配置回调 URL。安装器生成的控制命令支持官方扫码绑定，推荐直接执行：

```bash
xiu3 login
```

命令会显示 QQ 官方授权链接。用 QQ 扫码或打开链接完成授权后，命令会轮询结果，自动把 AppID 和加密 Secret 写入 `$HOME/xiu3/.env`，已有配置先备份为 `.env.bak`；宿主正在运行时会自动重启。Windows 使用 `& .\xiu3.ps1 login`。扫码授权需要网络连接，二维码过期或中断后重新执行命令即可。

也可以手动在 QQ 开放平台创建机器人，复制机器人 **AppID** 和 **AppSecret**，再按机器人所在场景启用对应事件权限，将 `QQ_BOTS` 从空列表改为以下形式：

```dotenv
QQ_BOTS='[
  {
    "id": "你的AppID",
    "secret": "你的AppSecret",
    "intent": {
      "c2c_group_at_messages": true,
      "guild_messages": true
    }
  }
]'
```

只使用其中一种场景时，可以删掉另一项 intent。AppSecret 不要提交到 Git 或公开日志。无需 QQ 官方机器人时保留 `QQ_BOTS=[]`；OneBot V11 可单独运行，也可以和 QQ 官方适配器同时使用。

配置完成后启动并查看日志：

```bash
cd "$HOME/xiu3"
xiu3 start
xiu3 login
tail -f .xiuxian3/nb.log
```

Windows 可用 `& .\xiu3.ps1 start` 启动，并用 `Get-Content .\.xiuxian3\nb.log -Wait` 查看日志。命令前缀由 `COMMAND_START` 控制；示例中的 `/` 可用 `/开始修仙` 触发命令。需要管理员权限时，将 `SUPERUSERS` 设置为管理员账号 ID 列表，例如 `SUPERUSERS=["123456789"]`；`XIUXIAN3_DATA_DIR` 指定 SQLite 和运行数据目录。

## 文档

- [安装文档](docs/installation.md)：Linux、Windows、Termux、Docker、一键安装与手动安装。
- [文档索引](docs/index.md)：玩法、配置和运行说明。
- [当前状态](docs/current-status.md)：已开放内容和待办事项。
