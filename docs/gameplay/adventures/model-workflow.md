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
- `secret_realm.demon_abyss.enter`、`secret_realm.demon_abyss.choose_node`、`secret_realm.demon_abyss.settle`
- `secret_realm.boundary_rift.enter`、`secret_realm.boundary_rift.choose_node`、`secret_realm.boundary_rift.settle`
- `secret_realm.ancestral_hall.enter`、`secret_realm.ancestral_hall.choose_node`、`secret_realm.ancestral_hall.settle`
- `secret_realm.time_fort.enter`、`secret_realm.time_fort.choose_node`、`secret_realm.time_fort.settle`
- `mainline.list_chapters`、`mainline.start_stage`、`mainline.claim_first_clear`
- `combat.replay.list`、`combat.replay.read`、`combat.replay.share`、`combat.replay.revoke_share`

## 统一要求

- `bounty.advance` 只能由白名单 operation 事件推进；同一事件 ID只计一次。
- v0.1 的草药补给从背包基线计算新增止血草，生产订单从接取时的已完成订单基线计算；
  进度读取不创建资产 operation，领取时才写入奖励和声誉流水。
- 每业务日每角色最多接取一条，且同时最多有一条未结/待领悬赏；过期领取会持久化 `expired`，不返还已获得物品。
- 秘境路线节点由服务端保存，玩家只能从当前允许节点选择；进入门票/体力先锁定，结算一次释放或消耗。
- `instance.secret_realm.boundary_rift` 使用独立队伍类型、运行记录、每周成员额度与结算事务；不得复用 `cave.boundary_realm` 战斗奖励。其固定路线、两场自动战、退款边界和恢复合同见[v0.3 冒险内容](content-v0.3.md#instancesecret_realmboundary_rift-合同)。
- `instance.secret_realm.demon_abyss` 将专属事务放在冒险域仓储 mixin；与其他秘境共享活动锁表，但不可并行运行。冻结路线、风险和版本快照，过期遭遇不得继续自动战，系统中止补偿只能回滚本 run 已记录的资源变化；详细合同见[v0.3 冒险内容](content-v0.3.md#instancesecret_realmdemon_abyss-合同)。
- `instance.secret_realm.time_fort` 使用独立队伍 run/成员表；入场冻结时序许可、战斗快照和时间风暴词缀，守时者自动战每三回合写入直接环境伤害动作。失败/过期不退成本，只有系统故障补偿才退款并释放周额度；详细合同见[v0.5 冒险内容](content-v0.5.md#instancesecret_realm-time_fort-合同)。
- 主线首次通关键为 `story_key:chapter:stage:player_id`；章节重试不能重复首通奖励。
- 斗法留影永不提供写资产接口，分享链接只含签名、过期时间和脱敏战报。
- 关闭内容时不新建会话；已有实例按原版本结算，无法结算则进入 `recovery_required` 并保留锁定原因。
