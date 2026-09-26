# v0.3 探索内容基线：跨界探索与界隙副本

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，跨界探索默认 `rule_version=exploration-0.3.0`；金丹前置备材使用 `exploration-0.3.1`。跨界探索统一保存阵营、污染/血脉、环境惩罚、队伍和池版本。

| `mode_key` | 前置 | 时长/成本 | 奖励池与保底 | 失败 |
|:--|:--|:--|:--|:--|
| `explore.demon_threshold` | 深渊门、金丹 L9、完成魔界引导 | 4 分钟 / 8 体力、2 精力；每日 6 次 | `gather.demon_threshold.v0.3`；神魂晶 1、魔核 1 | 未抵达或未完成引导不扣资源；已创建会话按冻结结果结算 |
| `explore.demon_abyss` | 魔渊地点、元婴、污染 <80 | 15 分钟 / 20 体力、污染 +10 | `loot.demon.abyss.v0.3`；魔核 1、魔界声望 15 或 `item.clue.demon_contract` 1 | 失败神魂 -2000 bp、虚弱 30 分钟 |
| `explore.beast_hunt` | 万兽山、元婴 | 15 分钟 / 20 体力 | `loot.beast.hills.v0.3`；妖血 1、妖界声望 15 或血脉线索 1 | 失败不发冻结奖励，不改变血脉稳定 |
| `explore.boundary_realm` | 界隙、2–5 队、门票 | 30 分钟 / 30 体力、`item.soul_crystal` 1 | 神魂晶 1、元婴材料 1；多人战 | 队伍全灭仅扣神魂，不掉永久装备 |

深渊门备材是元婴突破前的可重复玩家来源，不替代元婴后的魔渊探索、跨界贸易或队伍副本。魔渊额外事件池：魔核 45、声望 30、契约线索 15、心魔 10；万兽山：妖血 45、声望 30、血脉线索 15、祖灵事件 10。当前祖灵事件分支只保存为无资产结果，待独立事件切片接入。队伍副本奖励按角色贡献独立抽取，唯一物按贡献排序且保存排序；退出/掉线成员不获得未结算奖励。

魔渊与万兽多人队伍副本已使用独立 `PartyBattleSession`；祖灵机制只记录可清除祖灵，不伪造独立事件资产。探索仅写贡献，不直接发事件大奖；达领奖条件后必须单独调用 `event.claim_reward`。

世界探索事件由 events 域创建：`event.demon_invasion`、`event.beast_trade`、`event.boundary_rift`。探索仅写贡献，不直接发事件大奖；达领奖条件后必须单独调用 `event.claim_reward`。

跨界探索 running 后不可取消；超时 24 小时恢复任务按原池结算为失败或成功，依据已保存战斗结果。错误：`CROSS_REALM_REQUIREMENT_MISSING`、`POLLUTION_TOO_HIGH`、`PARTY_SIZE_INVALID`、`PARTY_MEMBER_INVALID`、`SOUL_CRYSTAL_INSUFFICIENT`、`SOUL_EXHAUSTION_ACTIVE`。关闭后停止新会话，旧会话结算、玩家可返回安全区。验收：污染/神魂变化一次；队伍前置整体拒绝；副本奖励按贡献不复制唯一物；跨界池/盟约更新不改变旧会话。
