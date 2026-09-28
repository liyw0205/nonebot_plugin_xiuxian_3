# 完成状态

## 已完成

- NoneBot 2 插件入口、QQ 官方适配器和 OneBot V11 适配器共用同一 application。
- QQ Markdown、蓝字命令和按键；OneBot V11 纯文本/合并转发降级。
- 境界、物品、任务、装备、地图、配方等内容从 `data/` JSON 读取。
- 内容文件头部重复的 `generated_at`、`schema_version`、`content_version`、`rule_version` 已移除，版本元数据集中到 `data/内容版本.json`。
- Linux、Windows、Termux 一键安装脚本，Linux/Windows/Termux 手动安装步骤，Docker 构建和 compose 文件。
- wheel 携带内置内容包；宿主 `data/` 可覆盖内容和保存 SQLite。
- 真实 NoneBot adapter 模拟测试、文档链接测试、内容校验和安装 smoke test。
- 真实 `nb run` 已验证：读取宿主 `.env` 的 `HOST`/`PORT`，成功注册并启动 OneBot V11、QQ 和插件；安装脚本使用普通 wheel，避免 editable finder 绕过 NoneBot 插件注册。

## 未完成或按范围关闭

- QQ/OneBot 的真实 token、账号和反向连接必须由部署者在宿主 `.env` 配置，仓库不提供凭证。
- Web 管理端写操作、跨服匹配、部分高阶副本和终局战斗仍按 `docs/current-status.md` 关闭。
- 历史数据库中的旧版本字段只能通过迁移和快照兼容，不能删除已有记录。
- 规则模块中用于旧操作回放的历史版本标识仍需逐域迁移；新代码不得继续增加散落的 `CONTENT_VERSION`、`RULE_VERSION` 或带版本号随机池。通用运行时版本和随机池已集中登记在 `data/内容版本.json`，历史字段不能从已有数据库记录删除。

## 验收入口

- 安装：`docs/installation.md`
- 内容：`test/test_content.py`
- 消息和适配器：`test/test_messaging.py`、`test/test_adapter_simulation.py`
- 全量：`$HOME/myenv/bin/python -m pytest -q`
