# 核心：修炼与构筑养成域

本域负责修炼/挂机经验、天赋树、体质、技能升级、法器强化和洗练。它可以改变成长与构筑，但每种成长必须有上限、成本、版本快照和失败保护。

## 术语映射

| 用户术语 | 修仙3稳定名称 | 稳定键前缀 |
|:--|:--|:--|
| 修炼/挂机经验 | 闭关修行结算 | `progression.retreat` |
| 天赋树 | 道脉天书 | `talent.tree` |
| 体质 | 体质根性 | `constitution.profile` |
| 技能升级 | 神通参悟 | `skill.growth` |
| 装备强化 | 法器祭炼 | `item.tempering` |
| 装备洗练 | 灵纹重铸 | `item.refinement` |

## 关键边界

- 生活挂机 `specials.idle` 不产修为；只有 `progression.retreat` 是受限的闭关修行会话，可以产境内修为。
- 闭关收益按离线最大窗口、洞府/功法/精力/食物快照结算，每日上限，不能离线无限累积。
- 体质是角色构筑基底，首版从资格快照选择 1 个主质；重塑需要稀有契约和冷却，不能随意切换。
- 天赋/技能/祭炼/重铸均不能绕过十层准入，也不能把低阶资源转换为跨境突破材料。
- 强化是可控等级成长；洗练是有限词条重掷，历史结果和消耗必须保留。失败不静默销毁唯一装备。

## 实体

`RetreatSession`、`TalentNodeState`、`ConstitutionProfile`、`SkillMastery`、`TemperingRecord`、`RefinementRecord` 均保存角色、目标/快照、成本、版本、状态、operation 与结果摘要。