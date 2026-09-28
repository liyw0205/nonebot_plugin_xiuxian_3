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
- 虚空塔 `tower.void_spire` 首个切片已完成：单人 1–30 层、风暴/回响路线、炼虚或虚空补给名望门槛、每周 2 次、独立运行/领奖表、首通/练习、失败计次、启动失败退款、图鉴和 QQ/OneBot 双适配器测试。
- 虚空塔 31–60 层已完成：碑铭/见证路线、合道或道统服务名望门槛、独立周限、首通图鉴/故事/展示称号、历史数据迁移与 operation 回放；`dispatch.dao_service` 已可产出道统服务名望。QQ/OneBot 专项和真实 `nb run` 已验证。

- 项目的构建、测试及 NoneBot/QQ/OneBot 依赖只指定最低版本，没有版本上限或精确锁定；新增回归测试防止重新引入上限。

## 未完成或按范围关闭

- QQ/OneBot 的真实 token、账号和反向连接必须由部署者在宿主 `.env` 配置，仓库不提供凭证。
- Web 管理端写操作、跨服匹配及未定义合同的后续副本仍按 `docs/current-status.md` 关闭；现有终局战斗已经开放。
- 虚空塔 61–90 层仍关闭；开放前必须补齐对应内容合同和快照测试。
- 历史数据库中的旧版本字段只能通过迁移和快照兼容，不能删除已有记录。
- 规则模块中用于旧操作回放的历史版本标识仍需逐域迁移；新代码不得继续增加散落的 `CONTENT_VERSION`、`RULE_VERSION` 或带版本号随机池。通用运行时版本和随机池已集中登记在 `data/内容版本.json`，历史字段不能从已有数据库记录删除。

## 验收入口

- 安装：`docs/installation.md`
- 内容：`test/test_content.py`
- 消息和适配器：`test/test_messaging.py`、`test/test_adapter_simulation.py`
- 全量：`$HOME/myenv/bin/python -m pytest -q`
