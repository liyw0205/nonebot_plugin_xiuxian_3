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

## 当前实现切片

`content-0.1` 已实现闭关修行的基础切片：`闭关预览`、`开始闭关`、`结算闭关`、`恢复闭关`，以及体质根性：
`体质预览`、`选择体质`、`我的体质`、`重塑体质`。
基础闭关使用 `progression.retreat.basic`，静养闭关使用 `progression.retreat.restful`；两者
均由独立 `retreat_sessions` 表和 operation ledger 持久化。静养所需的最小居所使用
`residence.town_room`，通过 `租住居所` 和 `我的居所` 管理。体质使用独立
`constitution_profiles` 表保存单一主质、效果、资格/道途快照和重塑冷却；道脉天书使用
`talent_node_states` 与天赋点流水保存当前首要道途的五阶线性节点。神通参悟已接入
`skill_masteries` 与技能心得流水，开放 `神通预览`、`我的神通`、`参悟神通 <技能>`。
低阶法器已接入独立 `equipment_instances`、祭炼流水和重铸流水，开放 `法器预览`、
`强化法器 <法器>`、`重铸预览`、`重铸法器 <法器>`；灵兽仍按内容开发总表逐个切片。
