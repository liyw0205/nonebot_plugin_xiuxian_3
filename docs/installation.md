# 安装与更新

本项目是 NoneBot 2 插件和宿主模板，要求 Python 3.11+。一键安装会建立 `$HOME/xiu3` 宿主和 `$HOME/myenv` 虚拟环境；宿主由 `nb run` 启动。

## Release 安装

默认从 GitHub Release 下载 `latest/download/project.tar.gz`。代理资产地址按顺序尝试，失败后回退 GitHub 直连；下载、解包或内容校验失败不会覆盖现有安装目录。

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

安装器会准备 Python 3.11+、venv、Git、curl 和构建工具，并默认使用清华 PyPI 镜像。Debian/Ubuntu 使用 apt，Fedora 使用 dnf/yum，Arch 使用 pacman，Alpine 使用 apk，Termux 使用 pkg。没有 sudo 时请先手动安装这些依赖。

可选参数：

```bash
bash scripts/onekey.sh install \
  --target "$HOME/xiu3" \
  --source "$HOME/.local/share/xiuxian3/source" \
  --source-mode release \
  --mirror accelerated \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

`--mirror` 可选 `direct`、`accelerated` 或 `custom`；自定义模式用 `--mirror-url URL` 指定完整的 `project.tar.gz` 地址。`--source-mode release` 强制使用 Release，`auto` 在仓库内运行时使用当前源码，在远程引导时使用 Release。

代理组包含 `gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`ghproxy.vip` 和 `gh-proxy.org`；每个地址失败后都会继续尝试，最后回退 GitHub 直连。

安装完成后：

```bash
cd "$HOME/xiu3"
xiu3 start
xiu3 status
```

更新使用 `xiu3 update` 或重新运行引导器的 `update`。Release 更新只替换安装器管理的源码缓存，保留宿主 `.env`、SQLite、`data/`、`runtime/` 和用户自己的 JSON。卸载需要显式确认：

```bash
xiu3 uninstall --yes
```

卸载会删除宿主目录，不删除共享 `$HOME/myenv`；请先备份数据库。

### Windows

```powershell
$installer = Join-Path $env:TEMP 'xiuxian3-onekey.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey_windows.ps1' -OutFile $installer
powershell -NoProfile -ExecutionPolicy Bypass -File $installer install
```

缺少 Python 3.11+ 或 Git 时，脚本会尝试通过 `winget` 安装。安装后的管理命令：

```powershell
Set-Location "$HOME\xiu3"
& .\xiu3.ps1 start
& .\xiu3.ps1 update
& .\xiu3.ps1 status
& .\xiu3.ps1 uninstall --yes
```

PowerShell 引导器也支持 `-Mirror direct|accelerated|custom`、`-MirrorUrl URL`、`-SourceMode release|source`。

### Termux

```bash
pkg update -y
pkg install -y curl
curl -fsSL https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh | bash -s -- install
```

脚本会用 `pkg` 补齐 Python、Git、curl 和 clang。可先运行 `termux-wake-lock`，不要在同一安装目录混用 Termux 和 proot-distro 的虚拟环境。

## 源码开发模式

贡献者或需要修改插件源码的用户必须显式选择：

```bash
git clone https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git
cd nonebot_plugin_xiuxian_3
bash scripts/onekey.sh install --source-mode source --mirror direct
```

源码模式保留 Git checkout；更新时要求工作树干净并使用 fast-forward。不要把 Release 安装目录当作开发 checkout，也不要在未备份时让安装器覆盖手工编辑的源码。

## 手动安装

适合已有宿主或需要自行管理依赖的用户：

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

只使用已有宿主时，安装 `requirements.txt`、在宿主里注册所需适配器和驱动，再用 `pip install --no-deps /path/to/nonebot_plugin_xiuxian_3` 安装插件。不要覆盖已有宿主的 `bot.py`、`pyproject.toml`、`.env` 或数据目录。

## Docker

```bash
cp -n docker/env.example docker/.env
# 编辑 docker/.env
docker compose build
docker compose up -d
docker compose logs -f
```

Compose 将宿主 `./data` 挂载到 `/app/data`，将 `./runtime` 挂载到 `/app/runtime`。容器内内容包只在挂载目录为空时初始化。

## 配置与接入

最小 `.env`：

```dotenv
ENVIRONMENT=prod
DRIVER=~fastapi+~httpx+~websockets+~aiohttp
HOST=0.0.0.0
PORT=8080
COMMAND_START=["/"]
SUPERUSERS=[]
QQ_BOTS=[]
XIUXIAN3_DATA_DIR=./data
```

OneBot V11 使用反向 WebSocket：`ws://服务器地址:8080/onebot/v11/ws`。QQ 官方机器人填写 `QQ_BOTS`，需要真实 AppID、Secret 和开放平台事件权限；`xiu3 login` 可辅助扫码绑定。QQ Markdown、蓝字和按键的本地合同测试不代表真实账号权限或客户端呈现已经通过。

## 检查

仓库修改后可以运行低成本校验：

```bash
bash -n scripts/onekey.sh scripts/install.sh scripts/install_termux.sh scripts/control.sh
python3 -m pytest -q test/test_installation_docs.py
git diff --check
```

标签 `vMAJOR.MINOR.PATCH` 的发布由 `.github/workflows/release.yml` 负责。工作流完成质量检查、隔离安装冒烟和 `project.tar.gz` 构建后，再创建 GitHub Release。
