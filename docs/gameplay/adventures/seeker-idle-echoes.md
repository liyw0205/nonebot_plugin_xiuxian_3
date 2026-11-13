# 寻道闲居回响

## 缺口与边界

寻道期已有两条可公开使用的闲居路线：`idle.seeker_town_inquiry` 要求青石镇地方名望
至少 10，`idle.seeker_herb_tending` 要求有效居所。两条路线均已有完整/逾时奖池、每日
限额、服务端计时、奖励事务与双适配器入口。剧情反馈不改变这些既有门槛、时长、
消耗、奖励或锁定内容。

## 三关路径

1. `seeker_echoes.1`：开始后沿公开通路结算抵达 `xuantian.new_town`。
2. `seeker_echoes.2`：开始后完整领取本人新安排的 `idle.seeker_town_inquiry`。
3. `seeker_echoes.3`：开始后完整领取本人新安排的 `idle.seeker_herb_tending`。

主线开始时冻结正文、行动、目标、奖励和重试提示。`travel_arrival` 只读取开始后的本人
`travel_sessions.status='arrived'`；`idle_claim` 只读取开始后的本人 `idle_assignments.status='claimed'`
并匹配路线。逾时、取消、旧安排、他人记录、其他地点、未结算行程或门槛不足均不推进，
主线保持 `running` 且不创建领取 operation。

## 玩家入口

QQ 官方与 OneBot V11 共用同一 application/repository。玩家可使用：

- `寻道闲居回响主线`
- `开始寻道闲居回响主线 <关卡名>`
- `领取寻道闲居回响主线奖励 <关卡名>`
- `前往 青石镇`
- `挂机预览 镇中问询`、`挂机预览 灵田照看`
- `开始挂机 <路线名>`、`领取挂机`

生活帮助指向真实命令；完整领取才算主线交班，逾时保底只按闲居合同发放，不替代剧情目标。
重复请求沿 operation ledger 回放，内容热更不改变已开始关卡快照。
