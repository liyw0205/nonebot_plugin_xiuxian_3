# v0.4 活动内容基线：领域前线与化神赛季

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=events-0.4.0`。

| `event_key` | 时长/地点 | 计分/门槛 | 奖励 |
|:--|:--|:--|:--|
| `event.domain_front` | 领域前线 4 小时 | 领域战胜利 +100、占点每分钟 +10；个人 >=100 | 领域核心碎片 5、世界功勋 100 |
| `event.ancient_domain_open` | 远古洞天 7 天 | 完成探索 5 次 | 领域核心碎片 10 |
| `event.abyss_depths` | 魔渊深层防守 3 小时 | 个人伤害/运输/净化按固定 action 分 | 三界功德 50；全服目标成功额外 50 |

`season.domain_war` 持续 21 天：领域前线贡献按贡献量计分、宗门建设每点 +2、化神配方成品每件 +5。前 1/2/3 名得碎片 20/15/10，4–10 碎片 5，11–50 得世界功勋 100。领域核心碎片是绑定材料，20 碎片可在赛季结束后由 `兑换领域核心 <赛季编号>`（`event.redeem.domain_core`）合成领域核心 1，每角色每赛季一次。

运行时将 UTC 时间按 4 小时对齐创建活动窗口；每个活动窗口切成 8 个 30 分钟轮次。
`xuantian.domain_front` 的参战入口要求化神 L1、已选领域、领域裂痕已恢复、宗门等级至少 4，
加入时冻结领域/宗门/境界快照并扣除 20 体力；每宗门每轮最多 20 名角色。`开始领域战` 是
服务端自动结算的胜利来源，`占点领域前线 [分钟]` 产生 1–30 分钟的服务端占点来源；
`贡献领域前线 战斗|占点 [来源operation]` 只投影属于当前参战角色、当前轮次且尚未消费的来源。
来源、贡献和领奖均使用独立 operation/唯一约束，轮次结束后冻结胜方领域、全服目标和个人贡献。

## 2. 化神许可任务

| `quest_key` | 目标 | 许可/奖励 | 限制 |
|:--|:--|:--|:--|
| `quest.domain_material_commission` | 完成领域材料委托 3 次 | 化神准备度 +300 bp、`item.ancient_fruit` 1 | 每角色一次；失败订单不计 |
| `quest.ancient_domain_line` | `explore.boundary_realm` 成功 3 次、交付神魂晶 3 | 远古洞天主线标记、准备度 +300 bp | 元婴可完成；不能要求已化神 |
| `quest.soul_transformation` | 上述两任务完成 + 跨界战胜利 1 次 | 化神突破许可、准备度 +600 bp | 只提供许可/准备度，不发化神境界 |

`event.redeem.domain_core` 输入 `item.domain_core_fragment` 20，输出 `item.domain_core` 1；成功后碎片消耗，重复 operation 回放同一核心实例。

所有事件开始时冻结领域版本、参与资格、敌人/地点和贡献公式；领域裂痕角色不能参加领域前线但可参与远古洞天非领域内容。错误：`DOMAIN_EVENT_REQUIREMENT_MISSING`、`DOMAIN_CRACK_ACTIVE`、`DOMAIN_CORE_REDEEM_ALREADY_USED`。关闭时不新计分，已创建奖励按轮次领取。验收：领域战贡献不因重放双加；碎片合成唯一；全服成功/个人门槛分离；赛季排名冻结。
