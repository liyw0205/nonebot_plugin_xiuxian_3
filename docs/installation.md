# 安装文档

本项目是 NoneBot 2 插件，不包含 QQ/OneBot token。先准备一个可运行的 NoneBot 2 宿主项目，再安装本插件并在宿主配置中加载 `nonebot_plugin_xiuxian_3`。

## Linux

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
git clone <你的 NoneBot 宿主项目地址> bot
cd bot
python3 -m venv "$HOME/myenv"
"$HOME/myenv/bin/python" -m pip install -U pip
"$HOME/myenv/bin/python" -m pip install -e "/path/to/nonebot_plugin_xiuxian_3[nonebot,onebot,qq]"
```

在宿主项目的 `.env` 或 `.env.prod` 中配置适配器和 `SUPERUSERS`，并在插件列表加载：

```python
nonebot.load_plugin("nonebot_plugin_xiuxian_3")
```

运行：

```bash
"$HOME/myenv/bin/python" -m nb_cli run
```

生产环境建议把 `XIUXIAN3_DATA_DIR` 指向 `/var/lib/xiuxian3`，并单独备份该目录。

## Windows

安装 Python 3.11 或更高版本（勾选 **Add Python to PATH**），然后在 PowerShell 执行：

```powershell
git clone <你的 NoneBot 宿主项目地址> bot
cd bot
py -3 -m venv "$HOME\myenv"
& "$HOME\myenv\Scripts\python.exe" -m pip install -U pip
& "$HOME\myenv\Scripts\python.exe" -m pip install -e "C:\path\to\nonebot_plugin_xiuxian_3[nonebot,onebot,qq]"
& "$HOME\myenv\Scripts\python.exe" -m nb_cli run
```

也可以使用 `python -m nb_cli run`，但必须确认命令使用的是刚创建的虚拟环境。数据目录示例：

```powershell
$env:XIUXIAN3_DATA_DIR = "$HOME\xiuxian3-data"
```

## Docker

项目当前不发布预构建镜像，使用宿主项目镜像安装本插件。一个最小 Dockerfile 如下：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . /app/nonebot_plugin_xiuxian_3
RUN python -m pip install --no-cache-dir -e "/app/nonebot_plugin_xiuxian_3[nonebot,onebot,qq]"
COPY bot /app/bot
WORKDIR /app/bot
CMD ["python", "-m", "nb_cli", "run"]
```

构建并运行，持久化数据库和内容数据：

```bash
docker build -t xiuxian3-bot .
docker run --rm -it \
  -e XIUXIAN3_DATA_DIR=/var/lib/xiuxian3 \
  -v "$PWD/xiuxian3-data:/var/lib/xiuxian3" \
  -v "$PWD/.env.prod:/app/bot/.env.prod:ro" \
  xiuxian3-bot
```

生产部署请使用 `restart: unless-stopped`、只读密钥挂载和定期备份卷；不要把 token 写入镜像层。

## Termux

```bash
pkg update
pkg install -y python git clang
git clone <你的 NoneBot 宿主项目地址> "$HOME/bot"
cd "$HOME/bot"
python -m venv "$HOME/myenv"
"$HOME/myenv/bin/python" -m pip install -U pip
"$HOME/myenv/bin/python" -m pip install -e "/path/to/nonebot_plugin_xiuxian_3[nonebot,onebot,qq]"
termux-wake-lock
"$HOME/myenv/bin/python" -m nb_cli run
```

建议将 `XIUXIAN3_DATA_DIR` 放在 `$HOME/xiuxian3-data`，并使用 Termux:Boot 或 `tmux` 管理后台进程。若在 proot-distro 容器内运行，请按照容器中的 Linux 步骤，不要混用原生 Termux Python 环境。

## 验证安装

```bash
"$HOME/myenv/bin/python" -m nonebot_plugin_xiuxian_3 --data-dir ./data
"$HOME/myenv/bin/python" -m pytest -q test/test_messaging.py test/test_content.py
```

QQ 模拟测试会验证 Markdown、蓝字和按键；OneBot 模拟测试会验证输出中没有这些平台专属消息段。
