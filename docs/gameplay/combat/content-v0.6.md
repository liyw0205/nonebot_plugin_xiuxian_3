# v0.6 战斗内容基线：道果、天劫与飞升终局

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=combat-0.6.0`。终局战最多 5 人；只有发起者的 `BattleResult` 可以推进境界/结局，协助者领取绑定世界功勋与终局材料。

| `enemy_key` | 气血/攻击 | 阶段与机制 | 发起者结算 |
|:--|:--|:--|:--|
| `enemy.dao_trial_avatar` | 100000 / 4000 | 根据发起者 `fruit_key` 复制对应道途状态；每 25% 气血转换阶段 | 道果进度、试炼完成 |
| `enemy.tribulation_heaven` | 150000 / 5500 | 雷劫/心劫/道劫三阶段；债务每 10 点使护盾 +200 bp | 天劫试炼成功、碎片/功勋 |
| `enemy.ascension_guardian` | 220000 / 7000 | 50% 气血开启留界诱惑；发起者选择继续/留界，选择保存 | 最终胜利或 `remain_in_world` 分支 |

终局战回合上限 30；超时采用自动防御 1 次后按失败结算，不允许长期挂机锁实例。协助者死亡不能由普通复起恢复，发起者仍可继续；全队失败时按 progression v0.6 增加天劫债，最终战失败冷却 7 天且不消耗飞升凭证。

| 行动/状态 | 规则 |
|:--|:--|
| `battle.tribulation_defend` | 发起者或协助者防御，使本回合天劫伤害 -3000 bp；每人每阶段最多 2 次 |
| `battle.dao_resonance` | 协助者贡献 1 点共鸣，最多 20；每 5 点为发起者护盾 +1000 bp 最大气血 |
| `battle.ascension_choice` | 仅守门人 50% 阶段、仅发起者；`continue` 或 `remain`，一旦提交不可撤销 |

所有阶段、债务难度、道果、共鸣、选择和奖励池保存于 `BattleSession`。`remain` 选择不算战斗失败，但立即结束为留界结局，会调用 `ascension.choose_ending`；`continue` 后才可击败守门人飞升。

错误：`TRIBULATION_BATTLE_REQUIREMENT_MISSING`、`TRIBULATION_DEBT_BLOCKED`、`ASCENSION_CHOICE_FORBIDDEN`、`ASCENSION_ASSIST_LIMIT`、`ENDGAME_REWARD_ALREADY_CLAIMED`。关闭后不创建新终局战，旧会话必须能完成或恢复为失败。验收：协助者不能获境界；债务护盾稳定；选择不能被重试改写；凭证失败不耗；奖励按角色/战斗唯一；历史终局回放完整。