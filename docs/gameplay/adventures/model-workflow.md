# 冒险域：模型、状态机与用例

## 状态机

```text
bounty: published -> accepted -> running -> completed/failed/expired -> reward_pending -> claimed
secret_realm: preview -> entered -> routing -> combat_pending -> cleared/failed/expired -> settled
mainline: locked -> available -> running -> cleared -> reward_pending -> claimed
replay: recorded -> indexed -> private/shared -> archived
```

## 用例

- `bounty.list`、`bounty.accept`、`bounty.advance`、`bounty.claim`
- `secret_realm.preview`、`secret_realm.enter`、`secret_realm.choose_node`、`secret_realm.settle`
- `mainline.list_chapters`、`mainline.start_stage`、`mainline.claim_first_clear`
- `combat.replay.list`、`combat.replay.read`、`combat.replay.share`、`combat.replay.revoke_share`

## 统一要求

- `bounty.advance` 只能由白名单 operation 事件推进；同一事件 ID只计一次。
- 秘境路线节点由服务端保存，玩家只能从当前允许节点选择；进入门票/体力先锁定，结算一次释放或消耗。
- 主线首次通关键为 `story_key:chapter:stage:player_id`；章节重试不能重复首通奖励。
- 斗法留影永不提供写资产接口，分享链接只含签名、过期时间和脱敏战报。
- 关闭内容时不新建会话；已有实例按原版本结算，无法结算则进入 `recovery_required` 并保留锁定原因。