# 安装文档

本仓库就是一个 NoneBot 2 插件，不是独立的 Web 服务。运行时需要一个宿主项目注册适配器，再加载 `nonebot_plugin_xiuxian_3`。仓库提供最小宿主模板、内容文件复制逻辑和四个平台入口。

## Linux

在插件仓库根目录执行：

```bash
bash scripts/install.sh install "$HOME/nonebot-bot"
cd "$HOME/nonebot-bot"
xiu3 start
```

脚本会创建或复用 Python 3.11+ 的 `$HOME/myenv`，安装 NoneBot CLI、OneBot V11、QQ 适配器和本插件，生成 `bot.py`、`pyproject.toml`、`.env`，并把 JSON 内容复制到宿主 `data/`。已有文件和已有内容不会覆盖。

安装完成后统一使用控制命令：

```bash
xiu3 start                 # 启动 nb run
xiu3 pause                 # 暂停进程
xiu3 resume                # 恢复进程
xiu3 status                # 查看 PID 和日志
xiu3 restart               # 重启
xiu3 update                # 更新插件和依赖
xiu3 uninstall --yes       # 删除宿主目录（不删除共享虚拟环境）
```

也可以再次执行 `scripts/install.sh update "$HOME/nonebot-bot"` 修复安装。安装器会检测 Python、venv、pip 和 JSON 内容，网络失败会自动重试三次，并在失败时保留现场和打印可定位的命令。

已有 NoneBot 宿主可以只安装插件：

```bash
"$HOME/myenv/bin/python" -m pip install '/path/to/nonebot_plugin_xiuxian_3[nonebot,onebot,qq]'
```

然后在宿主入口注册适配器，并在宿主 `pyproject.toml` 中显式列出这个独立插件：

```python
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.adapters.qq import Adapter as QQAdapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)
driver.register_adapter(QQAdapter)
nonebot.load_from_toml("pyproject.toml")
```

宿主 `pyproject.toml` 的插件段：

```toml
[tool.nonebot.plugins]
"@local" = ["nonebot_plugin_xiuxian_3"]
```

宿主目录内由 `xiu3` 控制 `nb run`，不直接运行插件模块。若 `$HOME/.local/bin` 不在 `PATH`，使用安装输出的完整路径或把它加入 `PATH`。

## Windows

在 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& .\scripts\install_windows.ps1 install "$HOME\nonebot-bot"
Set-Location "$HOME\nonebot-bot"
& .\xiu3.ps1 start
```

也可以在命令提示符运行：

```bat
scripts\install_windows.bat install %USERPROFILE%\nonebot-bot
```

脚本使用 `py -3` 创建 `$HOME\myenv`，保留已有宿主文件和 JSON 内容。

## Docker

项目根目录包含 `Dockerfile`、`docker-compose.yml` 和 `docker/` 宿主入口：

```bash
cp docker/env.example docker/.env
# 按需编辑 docker/.env 中的 QQ_BOTS、OneBot 地址和端口
docker compose build
docker compose up -d
docker compose logs -f
```

容器入口使用 `nb run`。`./data` 挂载到 `/app/data`，`./runtime` 挂载到 `/app/runtime`。空的 data 卷会在首次启动时自动补齐 JSON 内容，SQLite 数据也会保存在该目录。不要把 QQ token 或 OneBot 密钥提交到 Git。

## Termux

先安装基础工具：

```bash
pkg update
pkg install -y python git clang
```

在插件仓库根目录执行：

```bash
bash scripts/install_termux.sh install "$HOME/nonebot-bot"
cd "$HOME/nonebot-bot"
termux-wake-lock
xiu3 start
```

原生 Termux 使用 `$HOME/myenv`。如果在 `proot-distro` 中运行，请在容器内按 Linux 步骤重新创建虚拟环境，不要混用两套 Python。

## 手动安装

不使用一键脚本时，先在插件仓库根目录准备宿主目录，并把 `examples/nonebot/bot.py`、`examples/nonebot/pyproject.toml` 和 `examples/nonebot/.env.example` 分别复制为宿主的 `bot.py`、`pyproject.toml` 和 `.env`。宿主是独立的 NoneBot 项目，插件通过 `nonebot.load_from_toml` 显式加载，不放进其他插件目录。

Linux：

```bash
mkdir -p "$HOME/nonebot-bot/data"
python3 -m venv "$HOME/myenv"
"$HOME/myenv/bin/python" -m pip install -U pip
"$HOME/myenv/bin/python" -m pip install '/path/to/nonebot_plugin_xiuxian_3[nonebot,onebot,qq]'
cp examples/nonebot/bot.py examples/nonebot/pyproject.toml "$HOME/nonebot-bot/"
cp examples/nonebot/.env.example "$HOME/nonebot-bot/.env"
find data -type f -name '*.json' -exec sh -c 'mkdir -p "$HOME/nonebot-bot/data/$(dirname "${1#data/}")"; test -e "$HOME/nonebot-bot/data/${1#data/}" || cp "$1" "$HOME/nonebot-bot/data/${1#data/}"' _ {} \;
cd "$HOME/nonebot-bot" && "$HOME/myenv/bin/nb" run
```

Windows：

```powershell
New-Item -ItemType Directory -Force "$HOME\nonebot-bot\data" | Out-Null
py -3 -m venv "$HOME\myenv"
& "$HOME\myenv\Scripts\python.exe" -m pip install -U pip
& "$HOME\myenv\Scripts\python.exe" -m pip install "C:\path\to\nonebot_plugin_xiuxian_3[nonebot,onebot,qq]"
Copy-Item examples\nonebot\bot.py, examples\nonebot\pyproject.toml "$HOME\nonebot-bot\"
Copy-Item examples\nonebot\.env.example "$HOME\nonebot-bot\.env"
Set-Location "$HOME\nonebot-bot"
& "$HOME\myenv\Scripts\nb.exe" run
```

Termux：

```bash
mkdir -p "$HOME/nonebot-bot/data"
python -m venv "$HOME/myenv"
"$HOME/myenv/bin/python" -m pip install -U pip
"$HOME/myenv/bin/python" -m pip install '/path/to/nonebot_plugin_xiuxian_3[nonebot,onebot,qq]'
cp examples/nonebot/bot.py examples/nonebot/pyproject.toml "$HOME/nonebot-bot/"
cp examples/nonebot/.env.example "$HOME/nonebot-bot/.env"
cd "$HOME/nonebot-bot" && "$HOME/myenv/bin/nb" run
```

手动安装不会自动生成控制命令；可将 `scripts/control_windows.ps1`（Windows）或 `scripts/control.sh`（Linux/Termux）复制到宿主的 `.xiuxian3/`，再按安装器生成的参数调用。使用一键安装时会自动生成 `xiu3`/`xiu3.ps1`，并且只复制 `data/` 下的 JSON，不复制 SQLite、日志或缓存。

## 配置与验证

安装脚本生成的 `.env` 至少包含：

```dotenv
DRIVER=~fastapi+~httpx+~websockets+~aiohttp
HOST=0.0.0.0
PORT=8080
XIUXIAN3_DATA_DIR=./data
```

QQ 官方适配器的 `QQ_BOTS` 按适配器格式填写。OneBot V11 使用宿主 `.env` 的 `HOST` 和 `PORT`，由 `nb run` 启动 HTTP/WebSocket 入口，不需要额外的 WS 地址变量。插件只负责统一命令和业务处理：QQ 保留 Markdown、蓝字和按键，OneBot V11 自动降级为纯文本/合并转发。

离线验证：

```bash
"$HOME/myenv/bin/python" -m nonebot_plugin_xiuxian_3 --data-dir ./data
"$HOME/myenv/bin/python" -m pytest -q test/test_messaging.py test/test_content.py test/test_adapter_simulation.py
```

wheel 应包含 `nonebot_plugin_xiuxian_3/data/内容清单.json` 及其引用的所有 JSON 文件。
