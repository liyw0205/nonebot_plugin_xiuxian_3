# v0.5 战斗内容基线：炼虚虚空副本与宗门战争机关

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=combat-0.5.0`。开放自动回合 2–5 人虚空副本和 5 人跨服宗门战；创建时冻结虚力、锚、抗性、不稳定、服务器/宗门、规则版本和敌人池。玩家不提交战斗行动，服务端按快照和策略自动推进。

| `enemy_key` | 气血/攻击 | 阶段机制 | 胜利池 |
|:--|:--|:--|:--|
| `enemy.void_watcher` | 35000 / 1600 | 每 3 回合 `phase_shift`：普通攻击 -5000 bp，虚实技能正常 | 虚晶、航道声望 |
| `enemy.archive_keeper` | 42000 / 1800 | 化神完成三次界壁试炼或炼虚；回合 4/8 `rule_rewrite`：随机封锁一个非基础技能 2 回合，保存目标 roll | 档案、规则碎片、虚功勋 |
| `enemy.sect_war_engine` | 50000 / 1500 | 护城阶段 60/30%：需维修/破城二选一；未处理每回合范围伤害 | 堡垒贡献、跨服赛季奖励 |

| `skill_key` | 前置/效果 | 成本/限制 |
|:--|:--|:--|
| `skill.void_shift` | 炼虚；自身下次受击伤害 -4000 bp | 虚力 35 / 3 回合 |
| `skill.rule_rewrite` | 法修或阵法大师；解除一个封锁或令敌方技能冷却 +1 | 虚力 40、规则碎片 1 / 每场一次 |
| `skill.fortress_repair` | 器修或炼器大师；恢复战争机关 5000 bp 气血 | 虚力 30、云铁 2 / 2 回合 |

虚实切换和规则重写不能重置行动记录或使已结算资源返还；封锁目标由保存的 random roll 决定。战争机关战可选择 `repair` 或 `break` 分支，队伍第一次选择后锁定，不能在同场切换。

失败：虚空副本扣参与装备耐久 300 bp、可能设 `void_instability`；宗门战失败只扣轮次贡献，不扣普通背包物品。奖励按个人贡献/每周上限结算，跨服重复包需依据 `season.void_frontier.<week_id>` 去重。

错误：`VOID_BATTLE_RESOURCE_INSUFFICIENT`、`BATTLE_RULE_LOCKED`、`FORTRESS_BRANCH_LOCKED`、`CROSS_SERVER_PARTY_INVALID`、`SEASON_REWARD_CAP_REACHED`。关闭后旧战斗/轮次按原版本结算。验收：虚实伤害修正正确；随机封锁可回放；维修不双耗材料；分支不可切换；周奖励上限并发安全。
