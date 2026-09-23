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

公共项目由服务端业务周物化。贡献事务先校验项目轮次、资源和单次 30 点上限，再同步扣除资源、记录贡献和更新进度；达到所有资源目标立即进入 `active` 并冻结 7 天效果窗口。奖励结算只读取已完成项目，累计贡献至少 10 点才发放，并以 `(project_id, player_id)` 保证奖励唯一。
