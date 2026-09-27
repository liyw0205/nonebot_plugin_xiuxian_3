# 冒险域：模型、状态机与用例

## 状态机

```text
bounty: published -> accepted -> completed/expired -> claimed
secret_realm: preview -> entered -> routing -> combat_pending -> cleared/failed/expired -> settled
mainline: locked -> available -> running -> cleared -> reward_pending -> claimed
replay: recorded -> indexed -> private/shared -> archived
```

## 用例

- `bounty.list`、`bounty.accept`、`bounty.advance`、`bounty.claim`
- `secret_realm.preview`、`secret_realm.enter`、`secret_realm.choose_node`、`secret_realm.settle`
- `secret_realm.boundary_rift.enter`、`secret_realm.boundary_rift.choose_node`、`secret_realm.boundary_rift.settle`
- `mainline.list_chapters`、`mainline.start_stage`、`mainline.claim_first_clear`
- `combat.replay.list`、`combat.replay.read`、`combat.replay.share`、`combat.replay.revoke_share`

## 统一要求

- `bounty.advance` 只能由白名单 operation 事件推进；同一事件 ID只计一次。
- v0.1 的草药补给从背包基线计算新增止血草，生产订单从接取时的已完成订单基线计算；
  进度读取不创建资产 operation，领取时才写入奖励和声誉流水。
- 每业务日每角色最多接取一条，且同时最多有一条未结/待领悬赏；过期领取会持久化 `expired`，不返还已获得物品。
  训练傀儡悬赏只读取已结算的 `pve.training` 胜场，不自动生成战斗或代领战斗奖励；战斗域的训练傀儡会话与悬赏记录保持隔离。
- 秘境路线节点由服务端保存，玩家只能从当前允许节点选择；进入门票/体力先锁定，结算一次释放或消耗。
- `instance.secret_realm.boundary_rift` 使用独立队伍类型、运行记录、每周成员额度与结算事务；不得复用 `cave.boundary_realm` 战斗奖励。其固定路线、两场自动战、退款边界和恢复合同见[v0.3 冒险内容](content-v0.3.md#instancesecret_realmboundary_rift-合同)。
- 主线首次通关键为 `story_key:chapter:stage:player_id`；章节重试不能重复首通奖励。
- 斗法留影永不提供写资产接口，分享链接只含签名、过期时间和脱敏战报。
- 关闭内容时不新建会话；已有实例按原版本结算，无法结算则进入 `recovery_required` 并保留锁定原因。
