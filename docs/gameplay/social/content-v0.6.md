# v0.6 社交内容基线：道统、留界据点与终局协作

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=social-0.6.0`。终局个人结局始终独立：道侣、宗门和协助者不能替代发起者选择飞升或留界。

| 内容键 | 前置/成本 | 结算与限制 |
|:--|:--|:--|
| `dao.choose_route` | 宗门等级 >=6、至少 3 名合道投票、公共功勋 1000 | `guard_world/ascend/remain` 三选一，7 天锁定 |
| `dao.council_vote` | 合道成员、每周一次 | 投票方向；周日按多数结算，同票沿用上周 |
| `settlement.dao_hall` | 留界结局、世界功勋 2000、灵石 5000 | 核心成员 30、周维护 5000；72h 重建期 |
| `partner.endgame_task` | 有效道侣、双方终局会话未锁 | 共享协作任务，各得功勋；不改结局 |

投票效果：守界三界防御事件奖励 +1000 bp；飞升道果试炼奖励 +1000 bp；留界据点建设速度 +1500 bp。仅影响下一自然周创建的事件/订单，不回溯已创建会话。道统路线锁定期间不能切换；赛季结束可在新赛季重新投票。

留界据点被摧毁进入 `rebuilding` 72h：停止新建设/路线切换，已有成员保留，维护不收费；重建完成后恢复原路线。核心成员必须渡劫或留界，普通成员可作为访客但不占核心位。终局队伍协作者只得功勋/材料，不得改变发起者 `ending_state`。

错误：`DAO_COUNCIL_QUORUM_MISSING`、`DAO_VOTE_ALREADY_CAST`、`DAO_ROUTE_LOCKED`、`DAO_HALL_REBUILDING`、`ENDGAME_PARTNER_STATE_CONFLICT`。关闭后保留投票/据点读取和恢复，不发起新终局社交写入。验收：同票延续；投票不改历史事件；据点重建不丢成员；道侣不覆盖结局；协作者奖励唯一。