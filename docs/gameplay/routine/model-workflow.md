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

## 观测

记录窗口键、参与人数、领取/补领率、补签消耗、灵木产出、道契激活/撤销、机缘池消耗/保底、行卷等级、密令错误率、重复 operation 与管理员撤销。