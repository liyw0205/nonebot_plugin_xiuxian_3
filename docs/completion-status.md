# 完成状态

## 已完成

- NoneBot 2 插件入口、QQ 官方适配器和 OneBot V11 适配器共用同一 application。
- QQ Markdown、蓝字命令和按键；OneBot V11 纯文本/合并转发降级。
- 境界、物品、任务、装备、地图、配方等内容从 `data/` JSON 读取。
- 核心构筑内容已扩充：六大道途在九个开放境界各有稳定攻势与一条战术备选，共 108 条道途技能，技能名按招式特点区分且不直接拼接境界名；战斗消费爆发、辅御、持续、削弱、蓄力、中毒、灼烧和反伤，高阶备选以精英悬赏低权重传承残卷解锁；九境界各有两部功法，配置修为倍率、突破加成和不同战斗被动；法器、防具各 879 条，五档品质、道途/境界准入与攻击、防护、续航偏向均从 JSON 读取，每个道途/境界组合各有十六种选择；悬赏品质池按构筑筛选三类装备；战斗/修炼快照会消费配置效果。
- 内容 JSON 已移除无业务意义的 `generated_at`、`schema_version`、`content_version`、`rule_version` 字段；坏 JSON、重复对象键和缺失境界阈值会明确失败，不用 Python 默认表掩盖错误。
- 通用 JSON 变更缓存和 SQLite 连接初始化已收敛到 `xiuxian/utils/`，schema、事务与迁移由 `xiuxian/persistence/` 管理。
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
- 运行代码和数据库 schema 仍有历史 `content_version`、`rule_version` 字段及常量调用点，尚未完成清理；正式发布前直接移除这些无业务用途字段，不增加旧格式兼容迁移。
- 仓库仍保留 121 个 `content-v*.md` 旧页。有效方案信息尚未逐份核对；并入总表和领域文档后再移除重复页。
- 核心内容的数值平衡和各境界/道途来源覆盖仍需继续打磨；自动战斗尚不消费主动技能的资源消耗与冷却，未接入的效果不得配置为可用；生产配方目前不能仅靠新增 JSON 配置开放，悬赏矩阵也未覆盖所有组合。其他数据消费缺口以 `docs/content-data-contract.md` 的差距表为准。

## 验收入口

- 安装：`docs/installation.md`
- 内容：`test/test_content.py`
- 消息和适配器：`test/test_messaging.py`、`test/test_adapter_simulation.py`
- 全量：`$HOME/myenv/bin/python -m pytest -q`
