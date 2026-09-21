# v0.2 冒险内容基线：金丹悬赏、洞天二层与主线扩章

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=adventures-0.2.0`。v0.2 复用 v0.1 的轮次/快照/日志规则。

| 类型 | 稳定键/准入 | 参数与奖励 |
|:--|:--|:--|
| 悬赏 | `bounty.cloud_mine`：筑基 L4 或矿区许可 | 交付云铁 3；2h；灵石 120、名望 +8；每日 1 |
| 悬赏 | `bounty.elite_hunt`：金丹 L1、战斗资格 | 精英胜 1；4h；材料/称号碎片；失败不扣层 |
| 秘境 | `instance.secret_realm.mist_depth_2`：金丹 L1、`item.cave_pass_advanced` | 5 节点、15 体力；首通 `item.weapon.cloud_sword` 或图鉴线索；每周 1 |
| 秘境 | `instance.secret_realm.cloud_boat`：云舟票 | 3 节点、12 体力；首通航路图鉴/名望；每周 2 |
| 主线 | `story.mainline.xuantian.chapter_2` | `cloud_city`、`cloud_mine`、`formation_hall` 三章；每章 3 关；首通给地图/服务/生产线索 |
| 斗法留影 | `combat.replay.v0.2` | 保留 60 天/300 场；支持按战斗、塔、秘境筛选；分享仍 24h |

金丹/高阶悬赏奖励不直接发元婴突破材料；秘境重复收益受周上限。主线分支选定后保存，不能通过重试切换另一分支；关闭后已开始实例按 v0.2 池结算。