# v0.3 修炼与构筑养成内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=advancement-0.3.0`。三界构筑提供风险/服务差异，不允许通过宠物、技能或洗练跳过公共十层。

| 系统 | 稳定键/准入 | 成本与效果 |
|:--|:--|:--|
| 闭关 | `progression.retreat.nascent`：元婴 L1、洞天/宗门设施 | 6h、精力 12；修为 600–800；每日 1 |
| 体质 | `constitution.realm_affinity`：三界主线之一 | 一次选择地区亲和，地区行动成本 -3%，与主质并存但不可重复洗 |
| 天赋 | `talent.tree.*.tier3`：元婴 L3 | 8/13/21 点；开放 1 个协作/生产/探索分支，效果上限 +5% |
| 技能 | `skill.growth.tier3`：技能 7–9 | 三界材料/神魂点；升级成功固定，失败材料返 50% |
| 祭炼 | `item.tempering.realm`：元婴 L1 | 强化 7–9，成功 60/50/40%；失败耐久 -300 bp，等级不降 |
| 重铸 | `item.refinement.realm` | 可锁 2 词条；每次消耗神魂材料，不允许洗出高境属性 |
| 灵兽 | `beast.evolution.realm`：灵兽 20、亲和 60 | 品种专属材料 2；成功 90%，失败进入休养 2h；开 1 技能槽 |
| 灵骑 | `mount.evolution.realm`：灵骑 10 | 跨界鞍具；航道耗时 -8%、耐力 40；战斗不增加伤害 |

灵兽/灵骑辅助效果都写入行动快照，不实时改写玩家属性。