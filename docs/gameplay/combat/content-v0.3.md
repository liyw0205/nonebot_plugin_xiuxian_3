# v0.3 战斗内容基线：元婴跨界副本与阵营战

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=combat-0.3.0`。开放自动回合 2–5 人界隙副本、阵营战和固定规则 PvP 切磋；切磋无灵石/物品/修为奖励。玩家不提交战斗行动，服务端按双方快照和策略自动推进。

| `enemy_key` | 场景 | 气血/攻击 | 核心机制 | 奖励 |
|:--|:--|:--|:--|:--|
| `enemy.demon_overlord` | 魔渊副本 | 8000 / 520 | 每 3 回合全队污染 +8；气血 60/30% 阶段护盾 1000 | 魔核、功勋、魔界声望 |
| `enemy.demon_war_front` | `xuantian.war_front` 战场 | 600 / 35 | 固定单人自动战；战斗行动写入回放，伤害由事件域按每 100 点核验 | 无额外战斗奖励，贡献投影到 `event.demon_invasion` |
| `enemy.beast_ancestor` | 万兽副本 | 7500 / 480 | 血脉召唤 2 小怪；小怪存活时首领狂暴 +2000 bp | 妖血、功勋、妖界声望 |
| `enemy.boundary_watcher` | 界隙秘境 | 10000 / 600 | 回合 5/10 时间轴冲击，需至少 2 人防御否则全队神魂 -10 | 神魂晶、元婴材料 |

副本会话最多 5 人，至少 2 人；全员资格、体力、门票、跨界状态锁定后才创建。死亡角色进入 `downed`，队友可消耗神魂 25 复起一次；无人复起则战斗结束，该角色仅得贡献奖励。首领奖励按贡献/每角色上限独立结算；唯一物排序和 roll 固定在 `BattleResult`。

| `skill_key` | 效果 | 成本/限制 |
|:--|:--|:--|
| `skill.body.mountain_domain` | 队伍范围伤害 -2000 bp，3 回合 | 战意 40 / 每场一次 |
| `skill.spell.five_element_cycle` | 下次元素技能取得目标弱点 +1500 bp | 灵力 25 / 2 回合 |
| `skill.device.thousand_doll_array` | 召唤 2 机关，5 回合 | 灵力 35、每场一次 |
| `skill.demonic.abyss_communion` | 2 回合伤害 +2500 bp | 污染 20 / 每场一次 |
| `skill.beast.ancestral_form` | 4 回合派生属性 +1500 bp | 妖力 25、稳定 -8 / 每场一次 |
| `skill.soul.suppression` | 目标伤害 -1500 bp，2 回合 | 神魂 25 / 3 回合 |

阵营战按 `event.*.round_id` 进行，使用贡献积分而非直接掉落；切磋需双方确认、固定属性/规则版本、无奖励。错误：`BATTLE_CROSS_REALM_REQUIREMENT_MISSING`、`BATTLE_SOUL_POWER_INSUFFICIENT`、`BATTLE_REVIVE_LIMIT_REACHED`、`BATTLE_EVENT_NOT_ACTIVE`。关闭后旧副本结算，阵营轮次按原奖励池领奖。验收：护盾阶段只触发一次；复起不超过一次；贡献奖励与首领掉落分离；污染/神魂一次结算；切磋不产生资产。
