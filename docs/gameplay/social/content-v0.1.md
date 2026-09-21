# v0.1 社交内容基线：宗门、师徒、双人队伍与委托

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=social-0.1.0`。社交写操作都要求操作人、目标、原因（管理操作）和 `operation_id`；任何关系邀请在 24 小时后过期。

## 1. 宗门

| 内容键 | 前置/成本 | 状态与数值 | 权限/失败 |
|:--|:--|:--|:--|
| `sect.create` | 筑基、灵石 1000、未在宗门 | 成员上限 20、仓库 50 格、建设 0 | 名称唯一；扣费与创建同事务 |
| `sect.apply` | 未在宗门、未处于离宗冷却 | `pending`，24h 过期 | 宗主/副宗主/长老可批准；申请人撤销可释放 |
| `sect.leave` | 非宗主、无锁定职位/订单 | 24h 加入冷却 | 仓库借出/战斗/委托未结算则拒绝 |
| `sect.daily_build` | 成员、当天探索或生产成功 3 次 | 宗门建设 +1、个人贡献 +5 | 每人每日一次；按业务日唯一 |

职位：`member`、`deacon`、`elder`、`vice_leader`、`leader`。仓库权限默认：成员仅存取自己的受控申请物，执事可审核申请，长老可发任务，副宗主可批准/拒绝申请，宗主可改职位/解散。解散需要仓库清空、无进行中任务/订单/战斗，进入 24h `dissolving`，期间只允许撤销或结算；不直接删除历史贡献。

## 2. 师徒

`master.invite`：师傅筑基 L4 以上、同时徒弟 <3；徒弟为凡人–聚气 L6、无现任师傅。徒弟接受后关系 `active`，拒绝/过期不写关系。毕业条件：完成入道、达到聚气 L3、完成任意生产或常驻经营服务一次；`master.apprentice_graduate` 奖励徒弟地方名望 10、师傅贡献 20、双方服务信誉 +2。毕业奖励按关系 ID 唯一，关系变 `graduated`；解除关系 72h 冷却，不清除历史任务。师徒关系不直接发放修为、突破材料或突破概率。

## 3. 队伍与委托

`party.exploration_pair`：最多 2 人、同地点、双方确认窗口 5 分钟；创建后队长可开始探索，奖励按角色贡献分别生成，唯一装备不共享。队长离开且另一成员在线则转移队长，否则解散；队伍不会绕过个人地点、体力、境界或冷却条件。

`commission.v0.1` 仅支持疗伤丹/木纹剑：委托人先锁报酬（1–500 灵石）和要求，生产者接受后锁材料/精力/工具；完成后从报酬扣 2% 平台费给系统，失败返委托人 80% 报酬和未消耗材料。订单超时 24h：未接受全额解锁，processing 交恢复任务按生产快照结算。

错误：`SECT_ALREADY_JOINED`、`SECT_JOIN_COOLDOWN`、`SECT_PERMISSION_DENIED`、`MASTER_REQUIREMENT_MISSING`、`APPRENTICE_RELATION_CONFLICT`、`PARTY_LOCATION_MISMATCH`、`PARTY_CONFIRMATION_EXPIRED`、`COMMISSION_STATE_CONFLICT`。关闭 v0.1 后停止新关系/订单，旧关系可读、旧订单结算。验收：创建费不双扣；邀请双方确认；毕业只奖一次；离宗冷却生效；队伍奖励不复制；委托锁定/退款原子化。