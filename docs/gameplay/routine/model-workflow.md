# 道历与运营循环域：模型、状态机与用例

## 状态机

```text
window: scheduled -> open -> claimable -> claimed -> closed
makeup: eligible -> reserved -> claimed | expired
spirit_tree: dormant -> watered -> ready -> harvested -> cooldown
contract: pending -> active -> expired | revoked
pass: not_started -> active -> completed | closed
pass: completed -> closed
code: available -> claimed | expired | revoked
```

`gacha` 不使用长会话状态；每次抽取是一个原子 operation，失败不扣票/灵石。

## 用例

- `routine.claim_daily`、`routine.makeup_daily`、`routine.water_spirit_tree`、`routine.harvest_spirit_tree`
- `routine.activate_dao_contract`
- `pass.wayfaring.start`、`pass.wayfaring.claim`；状态查询由 `get_wayfaring_status` 投影既有来源
- `routine.roll_fate_pool`、`routine.claim_seven_day_goal`
- `routine.equip_title`、`routine.claim_achievement`
- `routine.redeem_code`

## 核心规则

1. 领取 operation 唯一；重复请求只回放原结果。行卷按周期、等级和奖励线核验领取资格，不预建逐级待领奖记录。
2. `business_date`、`business_week`、`business_month` 均由注入 Clock 和配置时区生成。
3. 任何失败在资产写入前返回；兑换码、道契和机缘池必须在同一事务检查库存/资格/幂等。
4. 断线不重复扣费；外部支付/投递失败不改变核心 entitlement，恢复任务使用凭证摘要重试。
5. 运营系统不得直接增加 `realm_layer`、`realm_cultivation`、`total_cultivation`、突破准备度、道果或天劫债。

## 当前事务流程

1. `routine.checkin.daily` 先读取 operation ledger，再锁定事务；`routine_checkins(player_id,
   target_date)` 的唯一键防止同日不同 operation 重复奖励。连续天数只读取 `claim_kind=daily`
   的相邻业务日，补录记录不会参与计算。
2. `routine.makeup.daily` 的 operation 回放优先于日期窗口检查；新请求再校验本月最近 3 日、
   月度 2 次上限、30 灵石余额，失败不会扣除资产。
3. 灵木先懒初始化 `spirit_trees`，浇灌以 `(player_id, cycle_no, business_date)` 唯一；第 7
   次只进入 `ready`。收获从当前奖池按 operation 派生的确定性种子选择结果，在同一事务写入
   `spirit_tree_harvests`、发放资产与地点名望，并开启 24 小时冷却。
4. 收获保存奖池键、种子摘要和实际奖励；重放直接反序列化历史 payload，不重新读取内容或抽取。
5. 称号由已落库来源 operation 投影到 `honor_titles`，装备状态单独保存在 `honor_states`；
   功业领取在同一事务内检查来源、写入 `achievement_claims`，并更新名望/信誉流水。
   功业、密令、道契和行卷的奖励均交给 `utils.player.grant_player_reward_actual`，地点键与上限由规则传入；
   资产、精力、名望、信誉、领取记录和 operation 共用同一事务，回复只展示实际到账数量。坏名望 JSON
   在角色状态事务入口拒绝，原 operation 可在故障解除后重试。
   关闭功业只展示“内容未开放”，不生成来源记录或奖励。
6. 机缘密令启动时从外部配置物化密令哈希和规则快照；兑换事务锁定库存，检查有效期、撤销、
   角色唯一领取和总库存，再原子更新资产、`redemption_claims`、库存计数与 operation。
   明文密令不进入数据库、日志或响应，重复 operation 只回放历史奖励。
7. 道契激活先在 billing 端口验证 Ed25519 凭证和角色主体，再在同一事务检查凭证唯一、商品
   价格和周期；激活奖励、`dao_contracts` 与 operation 一起提交。每日领取以
   `(contract_id, business_date)` 唯一，续期从旧周期结束日之后开始；撤销只改变未来状态，不回收已结算权益。
8. 机缘寻宝在同一事务锁定角色钱包/背包和 `fate_pools` 保底快照；单抽优先消耗机缘签，
   十连消耗固定灵石，确定性结果写入 `fate_rolls`、角色资产和 operation。保底、奖励清单、
   种子摘要和实际结果必须随 operation 保存，禁止按当前奖池重新抽取历史结果。

## 问道行卷事务流程

1. 开卷先检查 operation：相同输入回放原结果，不同输入返回冲突。新请求从
   `data/道历/行卷.json` 解析开放的 `pass.wayfaring`，校验逐级奖励、物品/称号引用、地方名望
   地点和任意开启星期的满级可达性。默认 28 日、30 级、每级 80 点、日上限 100、周上限 600；
   参数无效时不创建周期。现有周期尚未到期时不得另开一卷。
2. 起止日期使用服务端 UTC 业务日，首尾两日均属于周期，自然周从周一开始。周期记录冻结规则、
   行卷与来源名称、两条奖励线、奖励展示名、地方名望地点和上限。之后查询、计分和领奖只使用
   `snapshot_json`，不随现行内容变更；内容关闭只阻止新开卷，不影响已经承诺的周期。
3. 来源只读取当前角色在周期日期内的已结算 operation，按结算时间和 operation ID 确定顺序。
   八种允许来源及默认点数如下；来源名称和点数来自行卷 JSON，不允许客户端指定来源或数量。

| 已结算 operation | 来源键 | 默认点数 |
|:--|:--|--:|
| `player.start_seeking` | `player.start_seeking` | 10 |
| `routine.checkin.daily` | `routine.checkin.daily` | 20 |
| `routine.spirit_tree.water` | `routine.spirit_tree.water` | 5 |
| `routine.spirit_tree.harvest` | `routine.spirit_tree.harvest` | 30 |
| `production.complete` | `production.complete` | 25 |
| `bounty.claim` | `bounty.claim` | 25 |
| `exploration.settle` | `exploration.settle` | 20 |
| `routine.claim_dao_contract` | `dao_contract.daily` | 10 |

4. 每笔来源在同一周期只绑定一次，计入量同时受当日、当周和周期满级总量限制。达到日周上限的
   来源也记录为已处理，不能在下次查询重复补点；周期满级后不再新增积分事件。
   接取悬赏不计分，近郊采集不与探索结算重复计分。
   到期查询先投影周期内尚未处理的真实来源，再把周期关闭；已经满级的 `completed` 周期也按时关闭。
5. 领取先回放已提交 operation，再核验周期、等级、奖励线及未领取状态。未到期满级仍可领奖；
   到期后禁止新的免费或付费领取。付费线要求当前有效月道契，资格与领取结果一起留存；已提交
   operation 不因月道契失效而失去回放资格。
6. 奖励走既有共享角色资产/名望事务，称号走 `grant_player_honor_title`；地方名望按冻结上限
   封顶。积分事件、周期状态、奖励、称号、领取记录和 operation 在对应命令事务内一起提交。
   领取记录与回复仅记录实际到账并使用冻结展示名，重启或内容改名后不得改变结果。
7. JSON 重复字段、缺字段、错误类型、坏引用、无法满级的规则或损坏快照均明确拒绝；不以默认值
   或旧格式补齐。资产或 operation 写入失败须整笔回滚，原请求在故障解除后可重试。

## 七日入道事务流程

1. 首次 `player.start_seeking` operation 的服务端时间生成 `seven_day_campaigns.start_date`；
   状态查询和领奖都使用该快照，不读取客户端传入日期。
2. 目标来源必须是已落库的业务记录：问安、采集、生产订单、悬赏接取、派遣结算和入道
   operation；同一来源 operation 只能绑定一个目标，补做只能补领未领取的历史日数。
3. 领奖在同一事务内检查目标日期、来源、`seven_day_goal_claims(player_id, day_number)` 唯一
   键，通过共享角色奖励事务更新背包、灵石和地方名望并写 operation。D4/D7 名望上限读取青石镇地点内容，claim、operation 与回复只记录封顶后的实得数量；坏名望 JSON 或事务故障不得留下部分奖励。D5 只认试炼塔第一层胜利事件；D6 只认派遣结算事务
   投影的 `specials.dispatch.settled` 来源。目标查询/领奖不自行创建战斗或派遣状态。

## 观测

记录窗口键、参与人数、领取/补领率、补签消耗、灵木产出、道契激活/撤销、机缘池消耗/保底、行卷等级、密令错误率、重复 operation 与管理员撤销。
