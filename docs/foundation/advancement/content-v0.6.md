# v0.6 修炼与构筑养成内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=advancement-0.6.0`。合道、渡劫和终局只开放道统服务构筑；特色养成不得代替三次天劫、道果任务、最终战或结局选择。

| 系统 | 稳定键/准入 | 成本与效果 |
|:--|:--|:--|
| 闭关 | `progression.retreat.dao_union`：合道 L1；留界据点/道统服务 | 8h、精力 24；修为 3,000–3,800；每日 1 |
| 体质 | `constitution.dao_resonance`：合道 L3、道统旗标 | 选择 1 个服务/建设共鸣，公共项目效率 +5%；不改 `ending_state` |
| 天赋 | `talent.tree.*.tier6`：合道 L6 | 55/89/144 点；开放新篇章服务分支，不给道果/功勋 |
| 技能 | `skill.growth.tier6`：技能 16–18 | 道统普通材料/技能心得；每级 +5%，不能修改天劫成功率 |
| 祭炼 | `item.tempering.dao_service`：合道 L1 | 强化 16–18，成功 20/15/10%；失败只保留旧等级并进入 72h 冷却 |
| 重铸 | `item.refinement.dao_service` | 终局法器只可重铸服务/展示词条；禁止重铸道果、飞升、天劫词条 |
| 灵兽 | `beast.evolution.dao`：灵兽阶段 III | 道统服务材料 5；成功 60%；失败保留阶段，休养 24h |
| 灵骑 | `mount.evolution.dao`：灵骑等级 40 | 留界鞍具 1；公共运输耗时 -15%；飞升后冻结为只读历史实体 |

任何养成 operation 写 `resource.dao_fruit_progress`、`resource.ascension_merit`、`resource.tribulation_debt`、`ending_state`、飞升凭证或最终战资格，都必须返回 `ENDGAME_ASSET_FORBIDDEN`。