# NoneBot 修仙 3

`nonebot_plugin_xiuxian_3` 是一个面向 NoneBot 2 的文字修仙游戏插件。玩家可以创建角色、修炼功法、探索地图、接取悬赏、采集与生产、收集灵兽和装备，并在战斗与任务中持续成长。角色进度保存在 SQLite，玩法内容保存在可审查的 JSON 数据包中。

支持 **OneBot V11** 与 **QQ 官方机器人**。两种适配器共用玩家和玩法逻辑：OneBot 发送清晰的文本，QQ 在获得平台权限时可使用 Markdown、蓝字和按键，未获得权限时会自动降级。

## 功能

- 境界、功法、修炼、突破与道号
- 地图、探索、悬赏、战斗和成长奖励
- 采集、挖矿、生产、配方、商店与经济
- 灵兽、坐骑、装备、背包和图鉴
- 任务、每日玩法、成就与多人协作入口
- SQLite 事务存档和 JSON 内容包；内容目录可单独备份

常用入口示例：

```text
开始修仙
我的状态
修仙帮助
悬赏
探索
```

命令前缀由宿主的 `COMMAND_START` 决定，示例没有固定 `/` 前缀；QQ 群聊通常还需要 @机器人。

## 安装

### Linux 一键安装

无需先克隆仓库，安装器会创建独立宿主 `$HOME/xiu3` 和共享虚拟环境 `$HOME/myenv`：

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

远程安装和更新优先使用 GitHub Release 的 `latest/download/project.tar.gz`。代理下载失败会自动尝试其他代理并回退 GitHub 直连。也可以明确选择：

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install --mirror accelerated
```

可用代理包括 `gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`ghproxy.vip` 和 `gh-proxy.org`。安装选项、更新、卸载和故障处理见[安装文档](docs/installation.md)。

安装完成后编辑 `$HOME/xiu3/.env`，再运行：

```bash
xiu3 start
xiu3 status
```

### Docker

```bash
cp -n docker/env.example docker/.env
# 编辑 docker/.env，填入实际机器人配置
docker compose build
docker compose up -d
docker compose logs -f
```

`./data` 保存内容和 SQLite，`./runtime` 保存运行状态。凭据只放在 `docker/.env`，不要提交到 Git。

### Termux

```bash
pkg update -y
pkg install -y curl
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

启动前可执行 `termux-wake-lock`。`proot-distro` 环境请在容器内单独安装，不要混用两套 Python。

### Windows

在 PowerShell 中运行：

```powershell
$installer = Join-Path $env:TEMP 'xiuxian3-onekey.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey_windows.ps1' -OutFile $installer
powershell -NoProfile -ExecutionPolicy Bypass -File $installer install
```

脚本可通过 `winget` 准备 Python 3.11+ 和 Git。安装后：

```powershell
Set-Location "$HOME\xiu3"
& .\xiu3.ps1 start
```

### 手动安装

手动安装适合已有 NoneBot 宿主或需要自行管理虚拟环境的用户：

```bash
git clone https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git
cd nonebot_plugin_xiuxian_3
python3 -m venv "$HOME/myenv"
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
"$HOME/myenv/bin/python" -m pip install -r requirements.txt
mkdir -p "$HOME/xiu3"
cp examples/nonebot/bot.py examples/nonebot/pyproject.toml examples/nonebot/.env.example "$HOME/xiu3/"
mv "$HOME/xiu3/.env.example" "$HOME/xiu3/.env"
cp -R data "$HOME/xiu3/"
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" adapter install --no-restrict-version QQ
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" adapter install --no-restrict-version "OneBot V11"
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install FastAPI
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install HTTPX
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install websockets
"$HOME/myenv/bin/nb" --cwd "$HOME/xiu3" --python "$HOME/myenv/bin/python" driver install AIOHTTP
"$HOME/myenv/bin/python" -m pip install --no-deps .
cd "$HOME/xiu3" && "$HOME/myenv/bin/nb" run
```

源码开发模式显式使用本地 checkout，不下载 Release：

```bash
bash scripts/onekey.sh install --source-mode source --mirror direct
```

本地源码目录有未提交改动时，更新器会停止并保留现场；普通用户应使用 Release 模式。

## 最小配置与接入

编辑宿主目录的 `.env`：

```dotenv
ENVIRONMENT=prod
DRIVER=~fastapi+~httpx+~websockets+~aiohttp
HOST=0.0.0.0
PORT=8080
COMMAND_START=["/"]
SUPERUSERS=[]
QQ_BOTS=[]
XIUXIAN3_DATA_DIR=./data
# ONEBOT_V11_ACCESS_TOKEN=请替换为随机令牌
```

OneBot V11 反向 WebSocket 地址：

```text
ws://服务器地址:8080/onebot/v11/ws
```

NapCat 与 NoneBot 在 Docker Compose 同一网络时可使用：

```text
ws://xiuxian3:8080/onebot/v11/ws
```

QQ 官方机器人按 `QQ_BOTS` 的凭证和事件权限配置。配置后可用 `xiu3 login` 扫码绑定；不使用 QQ 时保持 `QQ_BOTS=[]`。

群聊 @ 消息可在 `QQ_BOTS` 的 intent 中启用 `c2c_group_at_messages`；具体字段以当前 QQ 适配器版本为准。

## 使用与更新

```bash
xiu3 start|stop|restart|status|pause|resume
xiu3 update
xiu3 login
xiu3 uninstall --yes
```

Release 更新会替换安装器管理的源码缓存并重新安装依赖，保留宿主目录中的 `.env`、SQLite 数据、`data/` 和 `runtime/`。用户自行编辑的 JSON 不会被静默覆盖。源码开发模式的更新只做 fast-forward 检查。

## 文档与数据

- [安装与更新](docs/installation.md)
- [发布分发约定](docs/release-distribution.md)
- [文档索引](docs/index.md)
- [当前状态](docs/current-status.md)
- [玩法总览](docs/gameplay/README.md)
- [适配器说明](docs/extensions/adapters/README.md)
- `data/`：JSON 内容定义和来源矩阵
- `runtime/`：运行时状态与日志（按部署方式挂载）

## 发布

推送形如 `vMAJOR.MINOR.PATCH` 的标签后，GitHub Actions 会先通过质量检查和隔离安装冒烟，再创建 GitHub Release 并上传统一资产 `project.tar.gz`。没有正式 Release 时请使用源码 checkout 的显式开发模式。

## 许可证

本项目采用 [MIT License](LICENSE)。
