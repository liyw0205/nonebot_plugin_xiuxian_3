# v0.5 内容包发布基线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

```yaml
content_version: content-0.5
rule_version: rules-0.5
release_mode: additive
requires: [content-0.4]
open_realms_added: [void_refining]
```

## 1. v0.5 新增开放内容

| kind | 稳定键 | 权威文件 |
|:--|:--|:--|
| realm/milestone | `void_refining`、`milestone.void_refining_late` | progression v0.5 |
| location/route | `void.first_route`、`void.archive_ruins`、`void.sect_fortress`、`cave.time_garden`、`void.void_market` | world v0.5 |
| mode/enemy | 三种虚空探索、三种炼虚首领 | exploration/combat v0.5 |
| skill/trait | 六条 `skill.*.void_*` / `trait.*.void_*` | paths v0.5 |
| recipe/item | 虚空加工、虚空刃、航标、加速阵、锚/晶体/档案 | production/items v0.5 |
| quest | `quest.break_void`、`quest.break_void_intro`、`task.archive_fragment.alpha/beta/gamma` | progression/events v0.5 |
| event/season | `event.void_storm`、`event.archive_unlock`、`event.time_garden`、`season.void_frontier` | events v0.5 |
| social/market | 虚空堡垒/航标/联盟、`market.void_*` | social/economy v0.5 |
| livelihood | `void_supply.*`、`facility.void_exchange_office`、`project.void_archive_repair`、`service.remote_artifice` | livelihood v0.5 |
| routine/adventures | `ritual.spirit_tree.void`、`gacha.fate.void_archive`、`story.void_archive`、`bounty.void_supply`、`instance.secret_realm.void_ruins` | routine/adventures v0.5 |
| advancement/companions | `progression.retreat.void_refining`、`talent.tree.*.tier5`、`item.tempering.void`、`beast.evolution.void`、`mount.evolution.void` | advancement/companions v0.5 |

`quest.break_void` 是炼虚突破许可：界壁试炼 3 次、交付 `item.void_archive` 1。`task.archive_fragment.*` 各要求一次不同虚空节点/战斗/生产贡献，完成三项才激活 `event.archive_unlock` 的新航道；任务进度按已结算 operation 唯一。

## 2. 校验、发布与关闭

验证虚空锚和晶体有可达来源、航道成本最少 1 锚、风暴/不稳定快照、虚空工坊维护、市场库存与跨服锁定、联盟不共享资产。虚空内容关闭只拒绝新进入；已开始探索、战斗、生产、订单和航线按原版本结算。