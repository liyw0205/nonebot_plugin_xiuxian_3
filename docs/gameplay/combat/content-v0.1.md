# v0.1 战斗内容基线：自动回合 PVE 与 PvP 预留

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=combat-0.1.0`。修仙 3 不是单人游戏：PVE 支持单人或多人协作，正式玩法包含双方/多方玩家 PvP；本快照只注册 `battle.duel.preview`，状态恒为 `locked`，不得创建匹配、排行或资产结算。训练战、近郊遭遇与雾隐守卫均采用自动回合规则，但战斗运行时必须等角色、属性、装备、技能、队伍和持久化基础完成后再开发。

## 1. 战斗会话与通用规则

`battle.start` 冻结角色 `StatSnapshot`、道途、装备耐久、地点、敌人定义、随机池和奖励池；状态：`created -> running -> won/lost/escaped/expired -> settled`。战斗开始后由服务端按冻结快照和战斗策略自动选择合法行动，玩家不能手动攻击、防御、选择技能、选择目标或提交伤害。每场最多 20 回合，回合超时 60 秒：服务端自动执行 `defend`（受到伤害 -2000 bp）且不消耗资源；连续 3 次超时判负。PVE 的撤退结果由开始前策略和服务端规则决定，运行中不提供手动逃跑指令；失败不掉永久物品，只损失本场已经消耗的技能资源和耐久。

命中：`hit_bp = clamp(8500 + attacker_initiative*20 - defender_agility*20 + skill_hit_bp, 2000, 9800)`。行动按 `random_pool=battle.<enemy_key>.v0.1` 固定命中/暴击/服务端行动策略；每条 `ActionRecord` 保存 roll、技能、目标、伤害、资源、状态和回合号。胜利只生成 `BattleResult(reward_pending)`；必须单独 `battle.claim_reward` 领取，角色/战斗唯一。

PvP 规则预留：双方或多方必须使用战斗开始时的角色、属性、装备、技能和匹配快照；服务端自动行动，
断线不暂停战斗，结果可完整回放；匹配按境界/保护规则分组，禁止刷分、协商输赢和永久资产损失。
在前置基础未完成前，上述规则只作为 `locked` 合同和测试夹具存在。

### 1.1 首个运行时切片：训练傀儡

`enemy.training_dummy` 是自动战斗运行时的首个可用垂直切片。玩家只能发送 `开始训练战`、
`领取战斗奖励` 和 `战斗回放`；客户端携带的技能、目标、伤害或回合参数一律拒绝。开始命令只创建
会话，随后由同一 application 调用内部 `run_turn` 直至 `resolve_battle`，因此聊天适配器不能直接推进
单回合。

训练战开始快照的基础攻击属性使用当前已存在的角色投影，避免在战斗域另建一套角色属性：

```text
max_hp = max(100 + body*4 + equipment_hp_affix, players.max_hp)
attack = 10 + floor(body/2) + weapon_temper_level*2 + equipment_damage_affix
initiative = max(8 + floor(agility/2) + equipment_initiative_affix, players.initiative)
agility = qualification.agility
```

仅快照内状态参与计算；战后修改资质、先手或装备不会改写历史回放。训练傀儡当前只使用
`skill.basic_attack` 与 `enemy_skill.dummy_tap`，每回合保存命中、暴击随机值、策略、目标、伤害和双方
剩余气血。胜利结算时参与的武器/防具耐久各扣 `50 bp`；三次服务端回合超时会自动防御并判负，失败只写
15 分钟战败调息，不扣永久物品。探索遭遇已按独立内容键接入单人自动回合；完整道途技能、多人 PVE 与 PvP 仍按后续切片开放。

## 2. 敌人与技能

| `enemy_key` | 前置地点/境界 | 气血/攻击/先手 | 技能与行为 | 胜利奖励池 |
|:--|:--|:--|:--|:--|
| `enemy.training_dummy` | 青石镇，感气 L1 | 80 / 8 / 8 | `enemy_skill.dummy_tap`：100% 攻击；不暴击、不逃跑 | 修为 20、灵石 5 |
| `enemy.wood_rat` | 近郊，凡人以上 | 45 / 8 / 10 | `enemy_skill.scratch`：110% 攻击，命中 +300 bp | 不单独发放；探索基础奖励由探索会话结算 |
| `enemy.iron_boar` | 近郊，感气 L3 | 100 / 15 / 7 | `enemy_skill.charge`：150% 攻击，冷却 2 回合 | 不单独发放；后续具名遭遇另行定义 |
| `enemy.bandit_apprentice` | 近郊短历练，聚气 L3 | 180 / 26 / 12 | `enemy_skill.blade_wave`：130% 攻击，附加流血 2 回合 | 灵石 20、修为 60、焦点丹 20% |
| `enemy.mist_guardian` | 雾隐洞天，聚气 L4 | 320 / 42 / 10 | `enemy_skill.mist_shield`：护盾 8000 bp 最大气血，持续 2 回合 | 不单独发放；探索基础奖励由探索会话结算 |

训练战奖励池在战斗开始时固定；探索遭遇只把战斗胜负交给探索会话，冻结的探索奖励不与敌人奖励叠加。`mist_guardian` 护盾先于气血承伤，过期或耗尽移除；同一回合不能重复释放。敌人不使用玩家道途资源。

| `skill_key` | 需求 | 效果 | 成本/冷却 |
|:--|:--|:--|:--|
| `skill.basic_attack` | 全部修行者 | 100% 攻击 | 无 / 无 |
| `skill.body.heavy_strike` | 体修 | `140% * body` 物理伤害 | 战意 10 / 1 回合 |
| `skill.spell.water_bolt` | 法修 | `150% * spirit` 法术伤害 | 灵力 18 / 1 回合 |
| `skill.device.scout_doll` | 器修 | 召唤机关，攻击为玩家 50%，3 回合 | 灵力 12 / 每场一次 |
| `skill.demonic.pain_exchange` | 魔修 | 当前气血 8% 换本次伤害 +4500 bp | 气血至少 20% / 2 回合，污染 +12 |
| `skill.beast.partial_transform` | 妖修 | 身法 +2000 bp，持续 3 回合 | 妖力 5 / 3 回合，稳定 -5 |
| `skill.support.quick_assessment` | 辅修 | 本场下一次物品/机关效果 +1000 bp | 精力 2 / 每场一次 |

## 3. 失败、耐久、奖励与验收

战斗失败：地点角色状态回到战斗前，气血恢复至 1，写 `battle_defeat` 15 分钟；雾隐守卫失败额外扣装备耐久 100 bp。胜利：参与武器/防具耐久 -50 bp，器修机关按定义扣耐久；耐久为 0 的实例下一场不能装备。逃跑成功无奖励，失败算一次敌方行动。

错误：`BATTLE_REQUIREMENT_MISSING`、`BATTLE_PLAYER_OCCUPIED`、`BATTLE_SKILL_LOCKED`、`BATTLE_RESOURCE_INSUFFICIENT`、`BATTLE_COOLDOWN_ACTIVE`、`BATTLE_REWARD_ALREADY_CLAIMED`。关闭 v0.1 时停止新战斗，running 战斗按原快照结算/超时判负。

验收：服务端自动选择的行动和敌方 roll 可重放；客户端不能提交或改写伤害、技能、目标和结果；同一行动不重复消耗；护盾与流血顺序正确；撤退不重抽奖励；失败不掉永久物品；领取奖励操作唯一；文本/按钮只调用同一 battle 用例，不能直接驱动战斗回合。
