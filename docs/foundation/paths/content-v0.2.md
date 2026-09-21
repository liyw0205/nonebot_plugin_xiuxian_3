# v0.2 道途内容基线：金丹分支

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=paths-0.2.0`。所有主动技能要求战斗/生产 operation，冷却按战斗回合或生产订单快照保存；同一技能的重复结算只返回原行动结果。

## 1. 首次分支

金丹 L3（入门完成）玩家可以执行一次 `paths.choose_specialization`，选择与首要道途匹配的两个分支之一。成本为灵石 2,000、`item.token.faction_seal` 1；选择只改变技能标签、资源偏重和可接任务，不改变公共境界、资质或已拥有物品。取消/超时不扣成本；成功后首版不可免费重选。

| 道途 | 分支键 | 偏重 |
|:--|:--|:--|
| `body` | `body.guard` / `body.breaker` | 承伤 / 破势 |
| `spell` | `spell.control` / `spell.burst` | 控制 / 爆发 |
| `device` | `device.puppet` / `device.array` | 傀儡 / 阵械 |
| `demonic` | `demonic.contract` / `demonic.devour` | 契约 / 吞噬 |
| `beast` | `beast.hunt` / `beast.kin` | 狩猎 / 族群 |
| `support` | `support.alchemy` / `support.artifice` / `support.formation` | 对应主辅修深化 |

## 2. 金丹能力

| 道途 | 被动键与效果 | 主动键、成本、冷却 | 前置与限制 |
|:--|:--|:--|:--|
| 体修 | `trait.body.iron_body`：护体乘区 +1200 bp | `skill.body.earthquake_fist`：基础 180%，20 战意，3 回合 | 金丹；最多命中 3 敌人；单场一次破势 |
| 法修 | `trait.spell.elemental_mastery`：元素乘区 +1500 bp | `skill.spell.chain_lightning`：3 目标，30 灵力，2 回合 | 金丹；同一目标第二跳伤害 50% |
| 器修 | `trait.device.multi_control`：操控上限 +1 | `skill.device.repair_doll`：恢复 3500 bp 耐久，15 灵力，3 回合 | 金丹；不能修复已销毁机关 |
| 魔修 | `trait.demonic.deep_contract`：侵蚀转化伤害系数 +1000 bp | `skill.demonic.shadow_bargain`：20 侵蚀换本次伤害 +8000 bp，4 回合 | 完成 `quest.demon_intro`；侵蚀不得低于 0 |
| 妖修 | `trait.beast.bloodline_awaken`：血脉效果 +1500 bp | `skill.beast.beast_roar`：目标迟缓 2 回合，25 妖力，3 回合 | 完成 `quest.beast_intro`；首领抗性按战斗内容定义 |
| 辅修 | `trait.support.master_crafter`：品质分 +1200 bp | `skill.support.emergency_refine`：生产时间 -3000 bp，额外 5 精力 | 主辅修等级 >=3；每订单一次 |

所有常驻/临时加成仍受属性域的 45%/100% 上限；超过部分返回截断来源。魔修主动使用后额外 +5 污染；妖修咆哮后化形稳定 -3；器修修复消耗对应机关耐久材料 1 个。

## 3. 结算、关闭与验收

- 错误：`PATH_SPECIALIZATION_MISSING`、`PATH_SPECIALIZATION_ALREADY_CHOSEN`、`PATH_RESOURCE_INSUFFICIENT`、`PATH_STATE_INSUFFICIENT`、`SKILL_COOLDOWN`、`CONTENT_CLOSED`。
- 观测：道途/分支、状态前后值、技能快照、成本、目标数、冷却、版本和结果。
- 关闭 v0.2 后：保留已选分支和技能快照；拒绝新选分支与新技能学习；已开始战斗/生产按原规则结算。
- 验收：选择不同输入复用 operation 冲突；技能资源不足不写冷却；多目标伤害和品质加成不能跨上限；生产加速重试不额外扣精力。