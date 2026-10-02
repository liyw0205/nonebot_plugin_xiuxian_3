# 安装文档

本仓库提供 NoneBot 2 插件和独立宿主模板。宿主使用 `nb run` 启动；不是独立 Web 服务，也不能作为其他插件的子插件加载。一键安装会创建 `$HOME/xiu3` 宿主和 `$HOME/myenv` 虚拟环境，默认通过清华源安装依赖。

## Linux 一键安装

直接在终端运行，不需要先克隆仓库：

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

安装器会检查 Python 3.11+、Git、curl、Python venv 和编译工具。Debian/Ubuntu 使用 `apt`，Fedora 使用 `dnf`/`yum`，Arch 使用 `pacman`，Alpine 使用 `apk`；需要 root 或 `sudo`。随后选择 GitHub 直连、代理组测速选优或自定义 Git 地址，创建宿主并检查依赖和 JSON 文件。

GitHub 访问较慢时，可代理下载引导脚本：

```bash
curl -fsSL https://gh-proxy.com/https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

引导脚本也可从 `ghproxy.net`、`ghfast.top`、`ghproxy.vip` 或 `gh-proxy.org` 获取；引导器运行后会对完整代理组测速并选择延迟最低的可用仓库源。

也可用参数指定仓库下载方式和目录：

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install --mirror accelerated --target "$HOME/xiu3" --source "$HOME/.local/share/xiuxian3/source"
```

支持 `--mirror direct|accelerated|custom`、`--mirror-url URL`、`--index-url URL`、`--venv PATH`。选择 `accelerated` 会测试 `gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`ghproxy.vip` 和 `gh-proxy.org` 的 Git refs 响应延迟，使用最快的可用代理；若克隆失败会依次尝试其他代理，代理组均不可用时回退直连。更新/卸载入口分别是：

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- update
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- uninstall --yes
```

卸载会删除宿主目录及 SQLite 数据，不删除共享虚拟环境或下载的源码；执行前先备份。

安装完成后配置 `$HOME/xiu3/.env` 并启动：

```bash
cd "$HOME/xiu3"
xiu3 start
```

如果公共命令目录不在 `PATH`，运行宿主内的 `./xiu3 start`。`xiu3` 还支持 `status`、`pause`、`resume`、`restart`、`stop`、`update`、`login`、`uninstall --yes`。

官方 QQ 机器人可以直接扫码绑定，不需要手动复制 Secret：

```bash
xiu3 login
```

命令会显示授权链接并轮询 QQ 绑定状态，成功后备份 `.env` 为 `.env.bak`，更新 `QQ_BOTS`；若宿主正在运行会自动重启。Windows 使用 `& .\xiu3.ps1 login`。授权链接过期或网络中断时重新执行即可。

## Windows 一键安装

PowerShell 下载并运行引导器：

```powershell
$installer = Join-Path $env:TEMP 'xiuxian3-onekey.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey_windows.ps1' -OutFile $installer
powershell -NoProfile -ExecutionPolicy Bypass -File $installer install
```

脚本在缺少 Python 3.11+ 或 Git 时尝试通过 `winget` 安装 Python 3.12 和 Git，并提供 GitHub 直连、代理组测速选优和自定义地址选择。若 GitHub 访问较慢，可把下载 URL 中 `raw.githubusercontent.com/` 前加以下任一域名：`gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`ghproxy.vip`、`gh-proxy.org`。没有 `winget` 时需先手动安装 Python 3.11+、Git 和 Windows App Installer。

编辑宿主 `.env` 后运行：

```powershell
Set-Location "$HOME\xiu3"
& .\xiu3.ps1 start
& .\xiu3.ps1 login
```

更新和卸载：

```powershell
& .\xiu3.ps1 update
& .\xiu3.ps1 uninstall --yes
```

也可以从已下载的仓库根目录运行 `scripts\install_windows.ps1 install "$HOME\xiu3"`。

## Termux 一键安装

Termux 需先有 `curl` 才能获取远程引导脚本：

```bash
pkg update -y
pkg install -y curl
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

引导器使用 `pkg` 安装 Python、Git、curl 和编译工具；虚拟环境使用 Termux 自带二进制依赖。启动前可执行 `termux-wake-lock`，再运行 `xiu3 start`。使用 `proot-distro` 时请在 Linux 容器内单独安装依赖和虚拟环境。

## Docker

在已取得的仓库目录中执行：

```bash
cp -n docker/env.example docker/.env
# 编辑 docker/.env，填入机器人配置
docker compose build
docker compose up -d
docker compose logs -f
```

容器入口通过 `nb run` 启动。`./data` 挂载到 `/app/data` 保存内容文件和 SQLite，`./runtime` 挂载到 `/app/runtime` 保存运行状态。不要将 QQ token 或其他凭据提交到 Git。

## 手动安装

### 独立宿主

手动安装需先取得仓库源码。下面示例使用 Linux；Termux 可将 `python3` 替换为 `python`，Windows 使用 `py -3` 创建虚拟环境。

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

Windows PowerShell：

```powershell
git clone https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git
Set-Location nonebot_plugin_xiuxian_3
py -3 -m venv "$HOME\myenv"
$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
& "$HOME\myenv\Scripts\python.exe" -m pip config --site set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
& "$HOME\myenv\Scripts\python.exe" -m pip install -r requirements.txt
New-Item -ItemType Directory -Force "$HOME\xiu3" | Out-Null
Copy-Item examples\nonebot\bot.py, examples\nonebot\pyproject.toml "$HOME\xiu3\"
Copy-Item examples\nonebot\.env.example "$HOME\xiu3\.env"
Copy-Item data "$HOME\xiu3\data" -Recurse
& "$HOME\myenv\Scripts\nb.exe" --cwd "$HOME\xiu3" --python "$HOME\myenv\Scripts\python.exe" adapter install --no-restrict-version QQ
& "$HOME\myenv\Scripts\nb.exe" --cwd "$HOME\xiu3" --python "$HOME\myenv\Scripts\python.exe" adapter install --no-restrict-version "OneBot V11"
& "$HOME\myenv\Scripts\nb.exe" --cwd "$HOME\xiu3" --python "$HOME\myenv\Scripts\python.exe" driver install FastAPI
& "$HOME\myenv\Scripts\nb.exe" --cwd "$HOME\xiu3" --python "$HOME\myenv\Scripts\python.exe" driver install HTTPX
& "$HOME\myenv\Scripts\nb.exe" --cwd "$HOME\xiu3" --python "$HOME\myenv\Scripts\python.exe" driver install websockets
& "$HOME\myenv\Scripts\nb.exe" --cwd "$HOME\xiu3" --python "$HOME\myenv\Scripts\python.exe" driver install AIOHTTP
& "$HOME\myenv\Scripts\python.exe" -m pip install --no-deps .
Set-Location "$HOME\xiu3"
& "$HOME\myenv\Scripts\nb.exe" run
```

`requirements.txt` 只安装 `nb-cli`。适配器及驱动通过 `nb adapter install` / `nb driver install` 安装，插件以 `--no-deps` 安装，避免 pip 重复解析宿主依赖。宿主模板注册适配器并显式加载 `nonebot_plugin_xiuxian_3`。

### 已有 NoneBot 宿主

只安装插件本身及适配器依赖：

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
"$HOME/myenv/bin/python" -m pip install -r /path/to/nonebot_plugin_xiuxian_3/requirements.txt
"$HOME/myenv/bin/nb" --cwd /path/to/host --python "$HOME/myenv/bin/python" adapter install --no-restrict-version QQ
"$HOME/myenv/bin/nb" --cwd /path/to/host --python "$HOME/myenv/bin/python" adapter install --no-restrict-version "OneBot V11"
"$HOME/myenv/bin/nb" --cwd /path/to/host --python "$HOME/myenv/bin/python" driver install FastAPI
"$HOME/myenv/bin/nb" --cwd /path/to/host --python "$HOME/myenv/bin/python" driver install HTTPX
"$HOME/myenv/bin/nb" --cwd /path/to/host --python "$HOME/myenv/bin/python" driver install websockets
"$HOME/myenv/bin/nb" --cwd /path/to/host --python "$HOME/myenv/bin/python" driver install AIOHTTP
"$HOME/myenv/bin/python" -m pip install --no-deps /path/to/nonebot_plugin_xiuxian_3
```

已有宿主请勿覆盖原有 `bot.py`、`pyproject.toml` 或 `.env`。确保入口注册正在使用的适配器，并在宿主 `pyproject.toml` 中将插件作为独立插件加载：

```toml
[tool.nonebot.plugins]
"@local" = ["nonebot_plugin_xiuxian_3"]
```

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

在宿主目录启动 `nb run`。OneBot V11 使用 `.env` 中 `HOST` / `PORT` 监听，不配置 `ONEBOT_V11_WS_URLS`。

## 配置与验证

宿主 `.env` 基础配置：

```dotenv
DRIVER=~fastapi+~httpx+~websockets+~aiohttp
HOST=0.0.0.0
PORT=8080
QQ_BOTS=[]
XIUXIAN3_DATA_DIR=./data
```

QQ 官方适配器按其配置格式填写 `QQ_BOTS`。QQ 支持 Markdown、蓝字和按键；OneBot V11 会降级为纯文本或合并转发。

安装脚本会检查宿主入口、Python 包、`nb` 命令及 JSON 内容。开发环境可运行：

```bash
"$HOME/myenv/bin/python" -m pytest -q test/test_documentation.py test/test_content.py test/test_messaging.py test/test_adapter_simulation.py
```
