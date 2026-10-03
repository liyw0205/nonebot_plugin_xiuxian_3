# v0.1 活动与任务内容基线：新手、日常与灵泉事件

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=events-0.1.0`。任务进度只由对应已结算 operation 投影，前端提交、消息文本或按钮参数不能直接写入。

## 1. 新手任务

| `quest_key` | 开放/目标 | 奖励 operation | 奖励 | 过期/失败 |
|:--|:--|:--|:--|:--|
| `quest.first_seeking` | 寻仙问道成功 | `quest.claim.first_seeking` | 灵石 100、`item.food.coarse_spirit_rice` 3 | 永不过期；每角色一次 |
| `quest.first_cultivation` | `player.enter_cultivation` 成功 | `quest.claim.first_cultivation` | `item.manual.basic_qi` 1、灵石 200 | 永不过期；入道主奖励与任务奖励分开，不能互相代替 |
| `quest.first_gather` | 任一 `explore.gather_outskirts` 成功结算 | `quest.claim.first_gather` | 止血草 2、修为 30 | 永不过期；战斗遭遇失败不计 |
| `quest.first_craft` | 任一生产订单 `completed` | `quest.claim.first_craft` | 灵石 50、`faction_reputation.xuantian` 2 | 永不过期；失败订单不计 |

任务完成与领取分离；领取按 `quest_key/player_id` 唯一。寻仙/入道的主 operation 已发基础资源，本表奖励是引导里程碑，必须各自保存来源与防重键。

## 2. 每日任务轮次

`daily.<business_date>` 首次查阅或领取时为角色冻结七项任务；按 JSON 中的分组和权重抽取，完成任意三项即可领取灵石 50、精力 5、青石镇名望 2；每日嘉奖不直接发修为。轮次结束后仍有 24 小时领取期限，逾期不补发。进度只投影轮次内本人已结算的来源，一条来源 operation 只能归入一项。

修行与历练包括修炼、近郊采集；常驻生活包括问安、生产、委托交付和灵田收获；其他历练包括悬赏、静养、运输、灵田养护和正式 PvE 胜利。候选、目标、来源白名单和任务说明以现行任务 JSON 为准；训练观战与切磋不计进度。配置变更只影响后续新轮次，已创建轮次继续使用冻结快照。

## 3. 世界事件：`event.spirit_spring`

| 字段 | 值 |
|:--|:--|
| 地点/时长 | `xuantian.spirit_field`，30 分钟 |
| 开放 | 感气、地点可达；每周三/周日 20:00 由稳定 job 创建 |
| 全服目标 | 成功采集 `item.herb.spirit_leaf` 100 份 |
| 个人贡献 | 每 1 份灵叶 +1，单角色本轮最多 30 |
| 个人领奖门槛 | 贡献 >=10 |
| 基础奖励 | 修为 150、灵石 100 |
| 完成加奖 | 事件成功时额外 `faction_reputation.xuantian` 10 |
| 领奖窗口 | 结束后 24 小时 |

事件轮次键为 `event.spirit_spring.<round_id>`；采集结算只能按原探索 operation 计贡献。`event.claim_reward` 按轮次/角色唯一，达到门槛但全服失败仍可领取基础奖励，不领取完成加奖。轮次关闭后停止新贡献，已 running 采集按创建时间归属原轮次。

错误：`QUEST_NOT_COMPLETED`、`QUEST_REWARD_ALREADY_CLAIMED`、`EVENT_NOT_ACTIVE`、`EVENT_CONTRIBUTION_INSUFFICIENT`、`EVENT_REWARD_EXPIRED`。关闭 v0.1 时停止新每日/事件轮次，已完成任务按窗口领取。验收：任务/事件进度不双计；领奖不双发；跨日轮次不漂移；事件全服失败与个人门槛分别结算；暂停角色不能领取但可读进度。
