# 常驻经营域：状态机

```text
residence: inactive -> leased -> active -> overdue -> released
plot: empty -> planted -> growing -> harvestable -> harvested
                         \-> withered
commission: published -> accepted -> delivered -> settled
                         \-> cancelled/expired
service_order: draft -> published -> accepted -> locked -> processing -> delivered -> settled
                                                          \-> failed/expired/cancelled
trade_route: preview -> created -> in_transit -> arrived -> settled
                                      \-> failed/expired
project: proposed -> active -> maintenance_due -> inactive
```

锁定材料、报酬、货物和维护费后才能进入可结算状态。相同 `operation_id` 回放同一状态/结果；相同 ID 而输入不同返回冲突。服务端业务日、地点库存、市场订单和角色会话锁共同决定配额，客户端时间与展示按钮不拥有结算权。

城镇委托按业务日冻结需求、报酬、地方名望键和地点名望上限；接取时复制该快照并只占用名额，
不扣物品。交付由共享角色状态事务同时扣除所需材料、发放灵石、增加地方名望和服务信誉，
委托状态、名望/信誉前后值与 operation 账本在同一事务提交。交付回复记录实际增加的名望和信誉，
封顶时不虚报额外所得；若已有名望超过旧单上限，奖励不再增长但不得扣回已有名望。重启、重放和
故障后重试均沿用已冻结的需求、报酬、名望键与上限，新的基础内容只用于新业务日委托。
名称解析不触发奖励校验，已接取委托可在内容关闭后交付；operation 优先读取历史结果，新接取才
校验当前开放规则。服务端日期不属于接取请求输入，跨日重放不占新名额。异常不得留下已扣材料、
已发报酬或半交付记录。

公共项目由服务端业务周物化。材料贡献先校验项目轮次、资源和单次 30 点上限，再同步扣除资源、记录贡献和更新进度；服务贡献必须在同一事务内核验已成功结算的来源事务、角色归属、来源状态与唯一使用，再记录固定服务点数，不再次扣费。达到所有资源目标立即进入 `active` 并冻结 7 天效果窗口。奖励结算只读取已完成项目，累计贡献至少 10 点才发放，并以 `(project_id, player_id)` 保证奖励唯一。
