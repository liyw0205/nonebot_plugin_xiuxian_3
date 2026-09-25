# v0.3 活动内容基线：三界事件、心魔与赛季

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=events-0.3.0`。

## 1. 三界事件

| `event_key` | 时长/地点 | 参与/贡献 | 个人奖励 |
|:--|:--|:--|:--|
| `event.demon_invasion` | `xuantian.war_front`，每周三 20:00 UTC 开始，持续 3 小时 | 元婴；战斗伤害每 100 +1、已结算运输 +10、已付款且仍 active 的个人设施维护 +15 | 贡献 >=50：世界功勋 50、魔界声望 20；宗门榜另结算 |
| `event.beast_trade` | 三界贸易口 7 天 | 跨界贸易每单 +10，提交妖血 +5 | 贡献 >=30：妖界声望 50、阵砂 10 |
| `event.boundary_rift` | 界隙 2 小时 | 界隙路线完成 +20、首领 +30 | 贡献 >=40：神魂晶 2、世界功勋 30 |
| `event.heart_demon_trial` | 元婴失败后个人事件 | 由突破失败会话创建 | 仅按 progression v0.3 选择结算，不作为公共排行 |

贡献按 `round_id/player_id/source_operation_id` 唯一；公共事件结束 24h 可领奖。心魔事件没有公共时间窗，超时 24h 按 `heart_demon.face` 自动结算。

当前运行时只开放事件轮次、运输来源投影和领奖；维修来源仅有仓储维护结算核验，战斗来源的
服务端核验已实现，但 `xuantian.war_front` 尚无玩家可达战斗入口，因此二者都不能写成已完成玩家路径。

## 2. `season.three_realms`

持续 28 天，榜单：阵营功勋、多人副本贡献、宗门贡献。赛季临时功勋/积分清零，永久物品、声望和已完成贸易不回滚；未完成赛季订单由经济域原路解锁。

赛季奖励：各榜前 3 给予绑定 `item.soul_crystal` 5/3/2 与世界功勋 200/120/80；4–100 给绑定神魂晶 1 与功勋 30。奖励按榜单/角色唯一，不同榜可各领一次。

## 3. 跨界主线与道途重构任务

| `quest_key` | 前置/目标 | 产出 | 限制 |
|:--|:--|:--|:--|
| `quest.demon_main_1` | 元婴、魔界声望 200、完成 `explore.demon_abyss` 2 次 | 开放 `demon.fallen_ruins`、魔界主线标记 | 每角色一次 |
| `quest.rebuild_path` | 元婴、三界声望各 1000、完成任一跨界主线 | `item.token.rebuild_path` 1、一次 `paths.rebuild` 资格 | token 永久绑定；资格不可重复领 |
| `quest.break_void_intro` | 元婴 perfect、完成 `explore.boundary_realm` 1 次 | 开放 `void.portal` 界壁试炼 | 不开放炼虚突破；炼虚许可在 v0.5 |

任务进度只接受已完成探索/战斗/贸易 operation。完成时冻结三界声望、主线、奖励和版本；后续声望变化不撤销资格。

错误：`THREE_REALMS_REQUIREMENT_MISSING`、`EVENT_CONTRIBUTION_INSUFFICIENT`、`HEART_DEMON_ALREADY_RESOLVED`、`SEASON_REWARD_EXPIRED`。关闭后已有心魔必须可结算，公共事件按轮次完成。验收：三界贡献不跨事件；心魔选择与突破 operation 关联；季末只清临时资源；跨榜奖励不相互覆盖。
