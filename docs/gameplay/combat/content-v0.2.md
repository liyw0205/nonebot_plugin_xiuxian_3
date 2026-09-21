# v0.2 战斗内容基线：金丹精英与双人协作

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=combat-0.2.0`。开放自动回合单人精英战和最多 2 人协作 PVE；PvP 继续 `locked`。玩家不提交攻击、防御、技能或目标，服务端按快照和策略自动推进。

| `enemy_key` | 准入 | 气血/攻击/先手 | 阶段与机制 | 胜利池/保底 |
|:--|:--|:--|:--|:--|
| `enemy.cloud_beast` | 云铁矿区、筑基 | 700 / 85 / 14 | `cloud_armor`：每 3 回合获得 1500 护甲，最多 3000 | 云铁 1、修为 120；30% 额外云铁 |
| `enemy.sect_traitor` | 玄天城、金丹 | 1100 / 140 / 18 | `firestorm`：第 4/8 回合范围 130% 法术；需队友分摊或防御 | 灵石 80、修为 300、声望 20 |
| `enemy.mist_elite` | 洞天二层、金丹 | 1800 / 190 / 15 | 初始护盾 400；破盾后 `exposed` 2 回合受伤 +1500 bp | 道品材料 1、修为 450；20% 金丹材料 |

战斗上限 25 回合；双人队伍必须同地点、双方确认，确认超时 5 分钟完整释放体力/门票。掉线成员按自动防御 2 次，之后离队；剩余成员可继续但奖励按贡献独立结算。战斗奖励池：`battle.elite.<enemy>.v0.2`，会话创建时固定。

| `skill_key` | 前置 | 效果 | 成本/冷却 |
|:--|:--|:--|:--|
| `skill.body.earthquake_fist` | 体修金丹 | 最多 3 目标 180% 伤害，命中后破势 +1 | 战意 20 / 3 回合 |
| `skill.spell.chain_lightning` | 法修金丹 | 最多 3 目标；每跳伤害为上次 50% | 灵力 30 / 2 回合 |
| `skill.device.repair_doll` | 器修金丹 | 机关恢复 3500 bp 耐久 | 灵力 15、耐久材料 1 / 3 回合 |
| `skill.support.array_bind` | 布阵主辅修 >=3 | 目标束缚 1 回合；首领抗性减半 | 灵力 20、阵砂 1 / 3 回合 |

错误：`BATTLE_PARTY_SIZE_INVALID`、`BATTLE_PARTY_CONFIRMATION_EXPIRED`、`BATTLE_ELITE_REQUIREMENT_MISSING`、`SKILL_TARGET_INVALID`。关闭 v0.2 后不建新精英战，已有会话按创建版本结算。验收：护甲刷新不叠超上限；破盾窗口正确；双人确认/掉线不复制奖励；范围技能目标数正确；PVP 无法创建资产战斗。
