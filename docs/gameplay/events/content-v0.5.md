# v0.5 活动内容基线：虚空风暴、档案解锁与炼虚赛季

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=events-0.5.0`。

| `event_key` | 时长 | 规则 | 奖励/风险 |
|:--|:--|:--|:--|
| `event.void_storm` | 2 小时 | 所有新航道会话使用风暴池；抗性按 stats v0.5 | 救援 +50 分；失败按池设不稳定 |
| `event.archive_unlock` | 7 天 | 三条 `task.archive_fragment.*` 完成后开放新航道 | 完成者虚功勋 50，首开宗门声望 100 |
| `event.time_garden` | 7 天 | 时序订单时间 -2000 bp，设施维护费 ×2 | 每角色最多绑定 3 单 |

`season.void_frontier` 持续 28 天：航道完成 +30、风暴救援 +50、跨服战胜利 +100、联盟合同完成 +20。前 3 宗门得虚空集市优先购买权 7 天（仅队列优先，不免费/不绕限额）。`task.void_frontier_weekly` 每周最多 5 次，单次虚空功勋 20、联盟积分 10；未领奖励进入待领取箱，季末 7 天后转换为绑定功勋。

## 2. 炼虚许可与档案任务

| `quest_or_task_key` | 目标 | 奖励/状态 | 上限 |
|:--|:--|:--|:--|
| `quest.break_void` | 完成界壁试炼 3 次、交付 `item.void_archive` 1 | 炼虚突破许可 | 每角色一次；失败试炼只计参与、不产档案 |
| `task.archive_fragment.alpha` | 第一航道成功探索 2 次 | 档案碎片 alpha、虚空功勋 20 | 每周一次 |
| `task.archive_fragment.beta` | 击败 `enemy.archive_keeper` 1 次 | 档案碎片 beta、虚空功勋 20 | 每周一次 |
| `task.archive_fragment.gamma` | 完成虚空加工订单 1 次 | 档案碎片 gamma、虚空功勋 20 | 每周一次 |

三种碎片任务完成后，由 `event.archive_unlock` 按角色/周唯一开放新航道资格。`quest.break_void` 只在三次界壁试炼与档案交付都完成后可领取；许可不自动消耗锚或创建突破。所有任务以来源 operation 去重，赛季关闭后已完成许可可保留。

风暴状态在会话创建时固定：事件中创建的会话继续用风暴池，即使事件结束；事件外会话不被追溯修改。错误：`VOID_EVENT_NOT_ACTIVE`、`TIME_GARDEN_ORDER_CAP`、`ARCHIVE_TASK_NOT_COMPLETE`。验收：风暴不重抽；生产加速不叠加；赛季队列权不绕市场限额；周任务上限；季末箱可恢复。