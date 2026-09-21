# v0.2 社交内容基线：金丹宗门与三人协作

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=social-0.2.0`。宗门最高等级扩展至 3，成员上限 40、公共仓库 100 格；同一玩家仍只能加入一个宗门。

## 1. 宗门任务

| `task_key` | 发布条件 | 目标/时限 | 宗门/个人结算 | 限制 |
|:--|:--|:--|:--|:--|
| `sect.cloud_mine` | 宗门等级 >=2 | 交付云铁 20 / 24h | 建设 +5、贡献 +20、灵石 100 | 执事每日最多发布 2 项 |
| `sect.mist_defense` | 等级 >=2 | 击败 `enemy.mist_elite` 1 / 24h | 建设 +8、贡献 +30、`merit` 10 | 金丹成员才能接取 |
| `sect.array_build` | 等级 >=2、阵堂开放 | 完成布阵 3 次 / 24h | 建设 +4、贡献 +15、阵砂 5 | 同一生产 operation 只计一次 |

发布操作冻结目标/奖励/时限；宗主/副宗主可取消 `draft/published` 任务，已提交材料不返还，未提交成员不扣资源。每成员每天最多领取 2 个宗门任务；贡献/建设与任务完成 operation 同事务。

## 2. 师徒、队伍与委托信誉

师徒毕业新增条件：筑基 L3、精英战胜利 1 次、完成 v0.1 原条件。毕业奖励改为徒弟地方名望 20、师傅 `merit` 30、双方服务信誉 +3；同一关系只结算一次，不直接发修为或突破材料。

队伍上限 3 人；队长通过 `party.transfer_leader` 需新队长确认，5 分钟过期。队长离线 10 分钟自动转给最早在线成员；若无人在线，队伍解散且不取消 running 副本。固定掉落分配：每个唯一物预先按 `contribution desc, join_time asc, player_id asc` 排序，排序快照写入战斗/探索结果。

委托信誉键：`commission.reputation.stranger/familiar/trusted/master`，完成成功订单 +1，生产失败且无违约不减，超时未处理 -1；阈值 0/3/10/30。`trusted` 才能接受金丹配方委托；信誉只影响委托准入，不加战斗数值。

错误：`SECT_TASK_DAILY_CAP`、`SECT_TASK_PUBLISH_CAP`、`PARTY_LEADER_TRANSFER_EXPIRED`、`PARTY_MEMBER_CAP`、`COMMISSION_REPUTATION_INSUFFICIENT`。关闭后已发布任务按原时限结算。验收：任务取消不误退已交材料；队长排序稳定；毕业不双发；信誉不因重试叠加；仓库容量并发检查。