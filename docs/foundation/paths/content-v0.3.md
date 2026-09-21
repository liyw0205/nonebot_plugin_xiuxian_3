# v0.3 道途内容基线：元婴跨界构筑

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=paths-0.3.0`。元婴跨界能力均要求 `realm_key=nascent_soul`，在 v0.2 及以下返回 `CONTENT_CLOSED`。

| 道途 | 稳定能力与数值 | 跨界状态/成本 | 限制 |
|:--|:--|:--|:--|
| 体修 | `trait.body.mountain_domain`：范围伤害 -2000 bp；战意上限 150 | 每次跨界战斗结束战意 -20 | 减伤受 8500 bp 硬上限 |
| 法修 | `trait.spell.five_element_cycle`：元素连续转换后下一次 +1500 bp | 每次转换消耗 12 灵力 | 同一元素不能连续两次转换 |
| 器修 | `trait.device.thousand_doll_array`：机关上限 +2 | 每场维护灵石 +15% | 超上限机关不能出战 |
| 魔修 | `trait.demonic.abyss_communion`：魔界伤害 +2500 bp | 魔界行动污染 +3 | 侵蚀软上限 100；超出触发内容事件 |
| 妖修 | `trait.beast.ancestral_form`：妖界六维派生 +1500 bp | 形态锁定至少 3 场行动 | 锁定中不能切换化形 |
| 辅修 | `trait.support.grand_artisan`：高阶品质分 +2000 bp | 每张高阶订单额外 3 精力 | 精力上限 +20，但不跨日累积 |

## 剧情重构：`paths.rebuild`

前置：元婴、三界声望各 `>=1,000`、完成 `quest.rebuild_path`、`item.token.rebuild_path` 1、灵石 50,000。先调用 `paths.preview_rebuild` 生成冻结计划，列出保留、冻结、转化和清理的技能/装备/状态；确认 operation 必须引用预览 ID，24 小时后过期。

成功：消耗 token/灵石，旧首要道途设为 `frozen`，新道途设为 `selected`、等级继承为 `max(1, old_level-2)`，污染/血脉/契约保留为历史状态，不允许普通洗点删除。失败或预览超时不扣资产。每角色只允许一次，重构记录永久保留。

错误：`PATH_REBUILD_QUEST_MISSING`、`PATH_REBUILD_LIMIT_REACHED`、`PATH_REBUILD_PREVIEW_EXPIRED`、`PATH_STATE_CONFLICT`。关闭 v0.3 后保留现有构筑，不创建新预览或确认。验收包括预览与确认同快照、重复确认回放、跨界加成正确受地点/状态约束、重构不重置公共境界。