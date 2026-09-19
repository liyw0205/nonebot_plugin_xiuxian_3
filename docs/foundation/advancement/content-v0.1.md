# v0.1 修炼与构筑养成内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=advancement-0.1.0`。首版开放感气成长、一个体质选择、基础天赋、基础技能参悟和低阶法器祭炼；失败保护不允许跳过十层。

## 1. 闭关修行

| `retreat_key` | 准入 | 时长/成本 | 收益 | 限制 |
|:--|:--|:--|:--|:--|
| `progression.retreat.basic` | 入道、`item.manual.basic_qi` | 2h；精力 4、灵米 1 | 境内修为 80–120（权重 25/50/25） | 每日最多 3 次，最多结算 8h |
| `progression.retreat.restful` | 凡人/修行者、有居所 | 4h；精力 2 | 精力恢复 8、境内修为 0 | 每日 1；不产战斗资源 |

开始时快照功法、道途、居所、灵米、精力、境界层数、环境和池版本；最多离线 24h，超过只按 8h结算。重复结算不重复发放。

## 2. 体质根性与道脉天书

- `constitution.profile`：入道时六选一：`constitution.iron_bone`（气血上限 +3%）、`constitution.spirit_root`（灵力上限 +3%）、`constitution.wind_step`（先手 +3%）、`constitution.craft_hand`（生产质量 +3%）、`constitution.beast_affinity`（灵兽亲和 +5）、`constitution.fortune_seed`（非保底掉落权重 +3%）。只选一个，保存快照。
- `talent.tree.body`、`spell`、`device`、`demonic`、`beast`、`support`：每树 5 节点，首节点免费，后续消耗 `resource.talent_point` 1/2/3/5；每层最多解锁 1 个，节点效果为 +1%–+3% 对应动作效率或一次性质量上限，不直接加突破率。
- 首次重塑体质要求 `item.token.constitution_reset`（首版不掉落，仅管理员测试），冷却 30 日，重塑会重新锁定构筑快照，不返还已用天赋点。

## 3. 神通参悟与法器祭炼/重铸

- `skill.basic_attack`、六道途 v0.1 主动技能可升 1–3 级；每级消耗技能心得 1/2、灵石 20/40/80，效果基础值 +3%/级；失败不扣技能心得。
- `item.tempering.basic_weapon`：木剑/棉袍强化 0→3，材料 1/2/3、灵石 20/40/80；成功率 100%/90%/75%，失败只损失本次材料，等级不降。
- `item.refinement.basic_weapon`：灵纹重铸的随机词条池 `damage+1`、`hp+5`、`initiative+1`，每次铁石 2、灵石 30；结果开始时抽取，失败保留旧词条，连续失败 3 次下次保底非空。

## 4. 灵兽与灵骑起点

- `beast.wood_rat`：首通近郊/故事奖励，等级 1–10，灵粮经验 10/次；每角色最多 3 只、出战 1 只；只提供采集发现率 +2%（上限）。
- `mount.bamboo_deer`：主线 chapter 1 首通契约；等级 1–5，运输速度 -3%/级，耐力 20；每角色 1 只。
- `beast.gear.sack_small`、`mount.tack.bamboo_saddle`：唯一实例，负重 +5/移动耗耐力 1；不可和玩家法器槽混用。

灵兽升级不产修为；灵骑出行失败进入休息 30m，不销毁实体。