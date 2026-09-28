# nonebot_plugin_xiuxian_3

一个面向 NoneBot 2 的修仙文字游戏插件，使用 SQLite 保存玩家状态，使用 `data/` 下的 JSON 保存境界、物品、任务、法器、地图和配方等可复用内容。

## 特性

- QQ 官方适配器：普通文本、原生 Markdown、蓝字命令链接和自定义按键。
- OneBot V11：普通文本和合并转发；自动移除 Markdown、蓝字和按键标记。
- 业务用例与适配器解耦，操作具备幂等键、版本快照和失败恢复语义。
- 内容包可校验、可替换；运行数据与源码分离。

境界展示使用中文格式，例如 `化神境一层`、`渡劫境十层`。文档中的 `v0.x` 只用于发布对照，运行时版本来自内容文件或历史操作快照，不应写死到业务文案中。

## 快速安装

这是一个需要宿主项目的 NoneBot 2 插件。安装脚本会创建宿主目录、虚拟环境、`.env`、`bot.py`、`pyproject.toml` 和可写的 `data/` 内容目录：

```bash
bash scripts/install.sh install "$HOME/nonebot-bot"
cd "$HOME/nonebot-bot"
xiu3 start
```

安装完成后使用 `xiu3` 控制宿主：`xiu3 start`、`xiu3 pause`、`xiu3 resume`、`xiu3 stop`、`xiu3 restart`、`xiu3 status`、`xiu3 update`、`xiu3 uninstall --yes`。脚本会保留已有配置和内容，不会删除共享的 `$HOME/myenv`。

也可以安装到已有宿主：

```bash
"$HOME/myenv/bin/python" -m pip install '/path/to/nonebot_plugin_xiuxian_3[nonebot,onebot,qq]'
```

Linux、Windows、Docker 和 Termux 的完整步骤见 [`docs/installation.md`](docs/installation.md)。仅运行规则测试可安装 `.[test]`；`.[nonebot,onebot,qq]` 会安装 NoneBot CLI 和两个适配器。

已完成、关闭范围和待办见 [`docs/completion-status.md`](docs/completion-status.md)。

## NoneBot 配置

安装脚本生成的 `bot.py` 会注册两个适配器，并通过宿主 `pyproject.toml` 加载这个独立插件；已有宿主也应在 `[tool.nonebot.plugins]` 中加入：

```toml
[tool.nonebot.plugins]
"@local" = ["nonebot_plugin_xiuxian_3"]
```

设置数据目录（不设置时使用宿主项目内可写的 `data/`）：

```dotenv
XIUXIAN3_DATA_DIR=/var/lib/xiuxian3
```

wheel 内置一份只读 JSON 内容包。宿主 `data/` 没有 `内容清单.json` 时会自动使用它；安装脚本和 Docker 会把 JSON 复制到宿主/挂载的 `data/`，便于运营方覆盖内容而不修改 site-packages。内容版本只在 `data/内容版本.json` 集中维护，业务 JSON 不再重复写生成时间和版本字段。

## 诊断运行

不启动 NoneBot 也可以检查 SQLite 和内容包：

```bash
"$HOME/myenv/bin/python" -m nonebot_plugin_xiuxian_3 --data-dir ./data
```

## 开发与测试

```bash
"$HOME/myenv/bin/python" -m pytest -q
"$HOME/myenv/bin/python" -m compileall -q nonebot_plugin_xiuxian_3
find data -name '*.json' -print0 | xargs -0 -n1 "$HOME/myenv/bin/python" -m json.tool >/dev/null
```

开发顺序、当前开放范围和待办以 [`docs/development-guide.md`](docs/development-guide.md)、[`docs/current-status.md`](docs/current-status.md) 和 [`docs/content-development.md`](docs/content-development.md) 为准。

## 目录约定

```text
data/                       # 只读内容包：境界、物品、装备、配方等
nonebot_plugin_xiuxian_3/  # 插件代码
examples/nonebot/           # 最小 NoneBot 宿主模板
docker/                     # 容器入口和环境示例
scripts/                    # Linux/Windows/Termux 安装脚本
docs/                       # 安装、架构、玩法和运维文档
test/                       # 单元、集成和双适配器模拟测试
```

数据库、日志、备份、密钥和用户数据不要提交到 Git。
