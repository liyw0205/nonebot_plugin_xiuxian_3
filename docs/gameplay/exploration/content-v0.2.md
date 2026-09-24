# v0.2 探索内容基线：金丹矿区、云舟试炼与洞天二层

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=exploration-0.2.0`。所有模式要求地点移动已结算；云舟票碎片是绑定任务物，不可直接交易。

| `mode_key` | 前置 | 时长/成本 | 池/产出 | 风险与上限 |
|:--|:--|:--|:--|:--|
| `explore.cloud_mine` | 云铁矿区、筑基、采矿 2 或矿区委托 | 2 分钟 / 8 体力、2 精力 | `gather.cloud_mine.v0.2`：云铁 1–4 | 30% 矿兽战；每日 6 |
| `explore.cloud_boat_trial` | 云舟渡口、金丹 | 5 分钟 / 12 体力、200 灵石 | `trial.cloud_boat.v0.2`：修为 600–900、票碎片 1–2 | 25% 风暴选择；每日 3 |
| `explore.mist_grotto_2` | 洞天二层、金丹、已进入 | 10 分钟 / 15 体力 | `cave.mist_grotto_2.v0.2`：道品材料 1–2、修为 900–1,300 | 40% 精英战；每日 2 |

矿区云铁权重为 1/2/3/4 = 25/40/25/10；矿兽战失败返还 1 云铁、不给额外矿。云舟风暴选择固定为 `wait`（延长 2 分钟，无损失）、`pay`（付 100 灵石，奖励 +200 修为）或 `turn_back`（返还 50% 体力、无奖励）；选择/超时均写同一探索 operation，超时默认 `wait`。

## 悬赏与结算

每日轮次生成 5 条，角色最多接 2 条：

| `offer_key` | 条件 | 目标/时限 | 奖励 |
|:--|:--|:--|:--|
| `bounty.cloud_iron` | 筑基 | 云铁 8 / 4 小时 | 修为 600、灵石 300 |
| `bounty.elite_guardian` | 金丹 | 击败 `enemy.mist_guardian` 2 / 6 小时 | `item.pill.core_condense` 1 |
| `bounty.array_service` | 聚气、宗门/邀请 | 布阵委托 2 / 8 小时 | `merit` 20 |
| `bounty.cloud_patrol` | 筑基 | 矿兽战胜利 3 / 6 小时 | 云铁 4、声望 20 |
| `bounty.boat_log` | 金丹 | 云舟试炼 1 / 2 小时 | 票碎片 2、修为 300 |

失败/过期不回收探索产出，奖励不发。当前运行时已接入 `explore.cloud_mine` 和
`explore.mist_grotto_2`；`explore.cloud_boat_trial`、云舟风暴选择和悬赏轮次仍未接入。
关闭 v0.2 后停止新模式，已开始洞天二层按池结算。验收：矿区工具/精力不足不扣体力；精力、
许可、内容版本和地点在开始时冻结；精英战不双掉道品材料；悬赏轮次奖励快照不随次日修改。
