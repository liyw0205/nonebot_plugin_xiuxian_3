# 道历与运营循环域：模型、状态机与用例

## 状态机

```text
window: scheduled -> open -> claimable -> claimed -> closed
makeup: eligible -> reserved -> claimed | expired
spirit_tree: dormant -> watered -> ready -> harvested -> cooldown
contract: pending -> active -> expired | revoked
pass: not_started -> active -> completed | closed
code: available -> claimed | expired | revoked
```

`gacha` 不使用长会话状态；每次抽取是一个原子 operation，失败不扣票/灵石。

## 用例

- `routine.claim_daily`、`routine.makeup_daily`、`routine.water_spirit_tree`、`routine.harvest_spirit_tree`
- `routine.activate_dao_contract`、`routine.get_pass`、`routine.claim_pass_level`
- `routine.roll_fate_pool`、`routine.claim_seven_day_goal`
- `routine.equip_title`、`routine.claim_achievement`
- `routine.redeem_code`

## 核心规则

1. 每个奖励先写 `pending_claim`，领取 operation 唯一；重复请求只回放原结果。
2. `business_date`、`business_week`、`business_month` 均由注入 Clock 和配置时区生成。
3. 任何失败在资产写入前返回；兑换码、道契和机缘池必须在同一事务检查库存/资格/幂等。
4. 断线不重复扣费；外部支付/投递失败不改变核心 entitlement，恢复任务使用凭证摘要重试。
5. 运营系统不得直接增加 `realm_layer`、`realm_cultivation`、`total_cultivation`、突破准备度、道果或天劫债。

## v0.1 首片事务流程

1. `routine.checkin.daily` 先读取 operation ledger，再锁定事务；`routine_checkins(player_id,
   target_date)` 的唯一键防止同日不同 operation 重复奖励。连续天数只读取 `claim_kind=daily`
   的相邻业务日，补录记录不会参与计算。
2. `routine.makeup.daily` 的 operation 回放优先于日期窗口检查；新请求再校验本月最近 3 日、
   月度 2 次上限、30 灵石余额，失败不会扣除资产。
3. 灵木先懒初始化 `spirit_trees`，浇灌以 `(player_id, cycle_no, business_date)` 唯一；第 7
   次只进入 `ready`，收获才会写入 `spirit_tree_harvests`、发放地方名望并开启 24 小时冷却。
4. 收获随机结果由 operation ID 派生确定性种子，持久化池键、种子摘要、奖励和版本；重放
   直接反序列化历史 payload，不重新调用随机池。

## 七日入道事务流程

1. 首次 `player.start_seeking` operation 的服务端时间生成 `seven_day_campaigns.start_date`；
   状态查询和领奖都使用该快照，不读取客户端传入日期。
2. 目标来源必须是已落库的业务记录：问安、采集、生产订单、悬赏接取和入道 operation；同一
   来源 operation 只能绑定一个目标，补做只能补领未领取的历史日数。
3. 领奖在同一事务内检查目标日期、来源、`seven_day_goal_claims(player_id, day_number)` 唯一
   键，更新背包/灵石/地方名望并写 operation。D5/D6 内容关闭时只返回未开放，不写入任何
   战斗或派遣状态。

## 观测

记录窗口键、参与人数、领取/补领率、补签消耗、灵木产出、道契激活/撤销、机缘池消耗/保底、行卷等级、密令错误率、重复 operation 与管理员撤销。
