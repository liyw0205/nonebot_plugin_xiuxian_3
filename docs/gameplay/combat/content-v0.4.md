# v0.4 战斗内容基线：化神领域战

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=combat-0.4.0`。开放最多 3 人领域战；会话创建时保存各领域、能量、力量、污染/血脉、地点和对抗快照。

| `enemy_key` | 气血/攻击 | 机制 | 胜利产出 |
|:--|:--|:--|:--|
| `enemy.ancient_domain_lord` | 18000 / 900 | `domain_suppress`：每回合削减 10 领域能量；能量 0 后玩家领域强制结束 | 古果、领域核心、功勋 |
| `enemy.abyss_general` | 15000 / 850 | `pollution_burst`：回合 4/8 全队污染 +12 | 深层魔核、魔界声望 |
| `enemy.ancestral_spirit` | 16000 / 820 | `bloodline_call`：召唤血脉影；不清除则首领恢复 5% 气血 | 祖灵血、妖界声望 |

新增通用领域动作：`skill.domain_break`（敌方领域/护盾 -3000 bp，领域能量 25，3 回合）、`skill.domain_guard`（队伍护盾 2500 bp 最大气血，能量 20，3 回合）、`skill.beast.ancestral_call`（妖修影协助 2 回合，妖力 20、稳定 -5）。领域技能必须受 paths/stats v0.4 冲突与上限规则约束。

领域战失败不降境界；每个参与者装备耐久 -200 bp，污染/稳定按实际动作保留。奖励先进入 `reward_pending`，按战斗/角色唯一领取。错误：`DOMAIN_BATTLE_REQUIREMENT_MISSING`、`DOMAIN_ENERGY_INSUFFICIENT`、`DOMAIN_CONFLICT`、`BATTLE_PARTY_SIZE_INVALID`。关闭后不建新领域战，已运行战斗按快照结束。验收：领域能量不负；压制/强制结束顺序正确；三人上限；首领召唤/治疗只结算一次；奖励回放稳定。