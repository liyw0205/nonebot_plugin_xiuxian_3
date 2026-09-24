# v0.6 探索内容基线：道源、天劫与飞升路

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=exploration-0.6.0`。此处 `explore.ascension_route` / `AscensionSession` 是早期方案快照，当前终局战由独立 `combat-final-0.1.0` 会话驱动，规则见[战斗用例](../combat/use-cases.md)；不要将该历史探索会话视为当前入口。

| `mode_key` | 准入 | 时长/成本 | 结算 | 失败 |
|:--|:--|:--|:--|:--|
| `explore.dao_origin_trial` | 合道、道果进度 >=500 | 60 分钟 / 20 体力、碎片 2 | 道果进度 150 或 250（难度快照） | 债务 +10、返回道源门、24 小时冷却 |
| `explore.tribulation_trial` | 试炼顺序前置 | 30 分钟 / token 1 | 按对应三次试炼固定奖励 | 进度不加，债务按试炼增加 |
| `explore.ascension_route` | 飞升候选、凭证锁定 | 90 分钟 / 无普通体力费 | 最终战/结局资格 | 债务 +25、7 天冷却、凭证不消耗 |

飞升路固定节点与 world v0.6 一致。`node.heart_test`、`node.dao_trial` 的选择/战斗结果保存于同一 `AscensionSession`；节点超时默认失败，不允许客户端重置节点。普通奖励只在节点首次成功时发放；任何失败重试均读取已获奖励列表，不双发。

道源试炼每日 1 次，债务 >=100 时拒绝。天劫试炼严格按 `trial.body_and_mind -> trial.three_realms -> trial.dao_choice` 顺序；最终战最多 1 发起者与 4 协助者，协助者只得绑定功勋。关闭 v0.6 后不开始新会话，既有 `AscensionSession` 允许按原快照完成或由管理员恢复用例标记失败。

错误：`DAO_TRIAL_DAILY_CAP`、`TRIBULATION_DEBT_BLOCKED`、`TRIAL_SEQUENCE_INVALID`、`ASCENSION_SESSION_BUSY`、`ASCENSION_COOLDOWN`。验收：失败无进度；token/凭证消耗语义正确；节点奖励唯一；协助者不获得结局；恢复不会重放随机/奖励。
