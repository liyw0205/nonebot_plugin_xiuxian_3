# v0.6 属性内容基线：道果、天劫债与飞升资格

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=stats-0.6.0`。

| `resource_key` | 范围 | 获取 | 消耗/阈值 |
|:--|:--|:--|:--|
| `resource.dao_fruit_progress` | 0–1,000 | 三次天劫试炼 100/180/250、终局内容补足 | 达 1,000 才可最终战；失败不加进度 |
| `resource.tribulation_debt` | 0–100+ | 试炼失败 +10/+15/+20，最终战失败 +25 | `>=100` 追加难度 2000 bp，禁止最终战 |
| `resource.ascension_merit` | 0–1,000 | 道统、终局贡献、试炼奖励 | 达 1,000 才生成飞升候选 |
| `ending_state` | `none/pending/ascended/remained` | 最终战成功与结局选择 | `ascended/remained` 不可逆 |

道果进度只能由 `tribulation.*` operation 写入；同一试炼轮次/角色的奖励唯一。债务在成功试炼后不自动清零，仅能由明确的道统服务每赛季降低最多 20，且不能低于 0。困难不是简单伤害倍率：`difficulty_bp` 必须写入天劫敌人护盾、环境或机制快照。

飞升候选：`resource.dao_fruit_progress>=1000`、`resource.ascension_merit>=1000`、债务 `<100`、三次试炼成功。候选状态冻结普通境界写入，允许结局选择；`ascended` 冻结三界经济资产，`remained` 保留道果并进入道统赛季规则。错误：`DAO_FRUIT_PROGRESS_INSUFFICIENT`、`TRIBULATION_DEBT_BLOCKED`、`ASCENSION_MERIT_INSUFFICIENT`、`ENDING_STATE_CONFLICT`。

关闭/恢复：v0.6 关闭不移除已存在债务或道果；结局记录作为不可变 operation 快照恢复。验收：失败不增长进度；债务/难度只应用一次；候选资格不能通过重试双发；两种结局互斥；飞升冻结不影响历史流水读取。