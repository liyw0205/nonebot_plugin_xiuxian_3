# nonebot_plugin_xiuxian_3

一个面向 NoneBot 2 的修仙文字游戏插件，使用 SQLite 保存玩家状态，使用 `data/` 下的 JSON 保存境界、物品、任务、法器、地图和配方等可复用内容。

## 特性

- QQ 官方适配器：普通文本、原生 Markdown、蓝字命令链接和自定义按键。
- OneBot V11：普通文本和合并转发；自动移除 Markdown、蓝字和按键标记。
- 业务用例与适配器解耦，操作具备幂等键、版本快照和失败恢复语义。
- 内容包可校验、可替换；运行数据与源码分离。

境界展示使用中文格式，例如 `化神境一层`、`渡劫境十层`。文档中的 `v0.x` 只用于发布对照，运行时版本来自内容文件或历史操作快照，不应写死到业务文案中。

## 快速安装

建议 Python 3.11+，并使用独立虚拟环境。完整的 Linux、Windows、Docker 和 Termux 步骤见 [`docs/installation.md`](docs/installation.md)。

```bash
python -m venv "$HOME/myenv"
"$HOME/myenv/bin/python" -m pip install -U pip
"$HOME/myenv/bin/python" -m pip install -e '.[nonebot,onebot,qq]'
```

仅运行规则测试可安装：

```bash
"$HOME/myenv/bin/python" -m pip install -e '.[test]'
```

## NoneBot 配置

在你的 NoneBot 项目中启用插件：

```python
nonebot.load_plugin("nonebot_plugin_xiuxian_3")
```

设置数据目录（不设置时使用项目内 `data/`）：

```dotenv
XIUXIAN3_DATA_DIR=/var/lib/xiuxian3
```

QQ 和 OneBot 适配器都由同一个 application 处理，不要为两个平台复制一套业务命令。

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
data/                       # 只读内容包：境界、物品、任务、装备、配方等
nonebot_plugin_xiuxian_3/  # 插件代码
docs/                       # 安装、架构、玩法和运维文档
test/                       # 单元、集成和双适配器模拟测试
```

数据库、日志、备份、密钥和用户数据不要提交到 Git。
