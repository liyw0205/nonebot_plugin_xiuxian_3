# v0.3 战斗内容基线：元婴跨界副本与阵营战

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=combat-0.3.0`。开放自动回合 2–5 人界隙副本、阵营战和固定规则 PvP 切磋；切磋无灵石/物品/修为奖励。玩家不提交战斗行动，服务端按双方快照和策略自动推进。

| `enemy_key` | 场景 | 气血/攻击 | 核心机制 | 奖励 |
|:--|:--|:--|:--|:--|
| `enemy.demon_overlord` | 魔渊副本 | 8000 / 520 | 每 3 回合全队污染 +8；气血 60/30% 阶段护盾 1000 | 魔核、功勋、魔界声望 |
| `enemy.demon_war_front` | `xuantian.war_front` 战场 | 600 / 35 | 固定单人自动战；战斗行动写入回放，伤害由事件域按每 100 点核验 | 无额外战斗奖励，贡献投影到 `event.demon_invasion` |
| `enemy.beast_ancestor` | 万兽副本 | 7500 / 480 | 血脉召唤 2 小怪；小怪存活时首领狂暴 +2000 bp | 妖血、功勋、妖界声望 |
| `enemy.boundary_watcher` | 界隙秘境 | 10000 / 600 | 回合 5/10 时间轴冲击，需至少 2 人防御否则全队神魂 -10 | 神魂晶、元婴材料 |

副本会话最多 5 人，至少 2 人；全员资格、体力、门票、跨界状态锁定后才创建。界隙、魔渊和万兽均使用独立队伍会话；魔渊队伍每名成员扣 20 体力并冻结污染，万兽队伍每名成员扣 20 体力并冻结血脉。死亡角色进入 `downed`，服务端按稳定成员顺序寻找存活队友，原子消耗 25 点神魂复起；每名被复起成员最多一次，神魂不足或无存活队友时不复起并结束战斗。复起、神魂扣除、贡献、污染和祖灵行动均写入队伍回放状态。首领奖励按贡献/每角色上限独立结算；唯一物排序和 roll 固定在 `BattleResult`，重复结算只读取已保存结果。

| `skill_key` | 效果 | 成本/限制 |
|:--|:--|:--|
| `skill.body.mountain_domain` | 体术伤害倍率 16000 bp，随参悟等级每级 +300 bp | 体修主动技能 |
| `skill.spell.five_element_cycle` | 术法伤害倍率 17000 bp，随参悟等级每级 +300 bp | 法修主动技能 |
| `skill.device.thousand_doll_array` | 机关攻击倍率 9000 bp，随参悟等级每级 +300 bp | 器修主动技能 |
| `skill.demonic.abyss_communion` | 伤害加成 7000 bp，随参悟等级每级 +300 bp | 魔修主动技能 |
| `skill.beast.ancestral_form` | 体术伤害倍率 15500 bp，随参悟等级每级 +300 bp | 妖修主动技能 |
| `skill.soul.suppression` | 神魂伤害倍率 15000 bp，随参悟等级每级 +300 bp | 复合/事件技能 |

开战时读取 `skill_masteries`，只冻结当前道途可用技能及等级效果；服务端优先选择已参悟的非基础主动技能，未参悟时回退 `skill.basic_attack`。技能选择、版本和实际伤害都写入 `ActionRecord`，客户端不能提交技能或伤害。

阵营战按 `event.*.round_id` 进行，使用贡献积分而非直接掉落；切磋需双方确认、固定属性/规则版本、无奖励。错误：`BATTLE_CROSS_REALM_REQUIREMENT_MISSING`、`BATTLE_SOUL_POWER_INSUFFICIENT`、`BATTLE_REVIVE_LIMIT_REACHED`、`BATTLE_EVENT_NOT_ACTIVE`。关闭后旧副本结算，阵营轮次按原奖励池领奖。验收：护盾阶段只触发一次；复起不超过一次；贡献奖励与首领掉落分离；污染/神魂一次结算；切磋不产生资产。
