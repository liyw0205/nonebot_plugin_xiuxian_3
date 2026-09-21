# v0.5 道途内容基线：炼虚虚实能力

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=paths-0.5.0`。所有能力要求炼虚与相应已选领域；每角色每天每项能力最多 3 次，次数按业务日和内容版本保存。

| 道途 | 稳定键 | 效果 | 成本/冷却/失败 |
|:--|:--|:--|:--|
| 体修 | `skill.body.void_step_body` | 首次致命伤害转为虚相，保留 1 点气血并免伤 1 回合 | 40 虚力；被真实伤害触发；同场一次；无虚力则正常受击 |
| 法修 | `skill.spell.void_spell` | 下一次术法无视 2000 bp 抗性 | 30 虚力，2 回合；若技能未命中仍消耗并写入结果 |
| 器修 | `skill.device.void_machine` | 一个机关本回合穿越护盾，伤害不穿透无敌 | 35 虚力、机关耐久 10%，3 回合 |
| 魔修 | `skill.demonic.void_contract` | 将最多 30 点侵蚀按 1:1 转为领域能量 | 侵蚀不得低于 20；每场一次；目标上限 150 |
| 妖修 | `trait.beast.void_bloodline` | 跨界环境惩罚减半，最低保留 200 bp | 被动；血脉稳定 <20 时失效 |
| 辅修 | `trait.support.void_refine` | 虚空材料加工损耗 -1500 bp | 被动；不影响非虚空配方和 NPC 回收 |

## 使用与结算

`paths.use_void_ability` 输入能力键、目标/订单、`operation_id`。预检查炼虚、每日次数、虚力、道途状态、地点与战斗/订单阶段；成功固定快照，扣资源，记录次数和结果。战斗能力由行动序列结算，生产能力绑定订单；网络重试只读取原行动，不再扣虚力/耐久/侵蚀。

错误：`VOID_ABILITY_LOCKED`、`VOID_POWER_INSUFFICIENT`、`VOID_DAILY_QUOTA_EXHAUSTED`、`VOID_STATE_REQUIREMENT_MISSING`、`VOID_TARGET_INVALID`。虚空区域关闭后拒绝新使用，但历史战斗和订单按创建版本结算。

验收：每天第四次拒绝不扣资源；虚相不能避开非伤害的强制结算；侵蚀转换不超过领域上限且保留污染流水；生产损耗按整数向上取整且不为负；同一操作回放同一触发时机。