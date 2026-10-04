# 常驻经营域：用例与验收

## 用例

- `livelihood.lease_residence` / `livelihood.renew_residence` / `livelihood.rest`
- `livelihood.plant` / `livelihood.maintain_plot` / `livelihood.harvest`
- `livelihood.list_commissions` / `livelihood.accept_commission` / `livelihood.deliver_commission`
- `livelihood.publish_service` / `livelihood.accept_service` / `livelihood.settle_service`
- `livelihood.preview_route` / `livelihood.start_route` / `livelihood.settle_route`
- `livelihood.list_projects` / `livelihood.contribute_project` / `livelihood.settle_project`
- `livelihood.get_profile`

## 错误码

`RESIDENCE_REQUIRED`、`RESIDENCE_RENT_DUE`、`PLOT_NOT_READY`、`PLOT_MAINTENANCE_MISSED`、`COMMISSION_STOCK_EXHAUSTED`、`COMMISSION_ALREADY_ACCEPTED`、`SERVICE_REPUTATION_INSUFFICIENT`、`SERVICE_ESCROW_CONFLICT`、`ROUTE_QUOTA_EXHAUSTED`、`ROUTE_CARGO_LOCKED`、`LOCAL_REPUTATION_INSUFFICIENT`、`PROJECT_CONTRIBUTION_LIMIT`、`PROJECT_RESOURCE_INVALID`、`PROJECT_SOURCE_INVALID`、`PROJECT_SOURCE_ALREADY_USED`、`PROJECT_ALREADY_COMPLETE`、`PROJECT_NOT_READY`、`LIVELIHOOD_CONTENT_CLOSED`。

## 验收

1. 凡人可在不拥有修为/境界层数的情况下租居所、接城镇委托、种植和运输。
2. 种植、运输和服务订单不直接增加 `realm_cultivation` 或 `total_cultivation`。
3. 同一地块/委托库存/货物在并发请求下只被锁定一次。
4. 维护逾期和订单过期按快照结算/释放，不双扣、不双返。短途运输当前只支持抵达结算，尚无主动取消、运输失败或过期退货入口；结算故障回滚保留出发成本，不等同于退货。
5. 名望和信誉改变只解锁服务槽、折扣、委托类型或公共建设参与，不增加伤害、突破率或境界层数。
6. 文本、按钮和 Web 入口都调用同一 application DTO；渲染失败不改变订单、地块或资产。
7. 每周只物化一个公共项目；任一单次贡献不得超过 30 点，资源不足时角色资产和项目进度都不变化。
8. 公共效果在完成时固定 7 天窗口；同一角色的个人奖励至多结算一次，且不改变修为或突破准备度。
9. QQ 与 OneBot V11 真实事件归一化后必须到达同一公共项目 application DTO。
10. 服务贡献只能引用当前角色已成功结算的运输、净化或灵兽事务；进行中、失败、过期、他人来源和重复来源均不得改变项目或角色状态。
11. 委托交付共用角色状态内核，材料、灵石、地方名望、信誉、交付记录和 operation 一并提交；名望键与上限冻结自地点内容，信誉上限遵守共享状态合同。配置改值、名望高于旧单上限、名望地点变更或关闭后的交付/重放、跨日接取重放、重启、不同输入冲突、交付竞争及各写入阶段故障回滚必须验证，异常声望 JSON 不得静默重建。
12. 委托列表和接取回复显示物品名称、委托名称与中文状态，不展示内容稳定键；交付回复只展示实际所得，QQ 官方与 OneBot V11 使用同一用例和结果。
13. 运输规则实际读取生活 JSON，临时修改报酬、名望地点及上限、货值、成本、耗时与准入条件后行为必须变化；坏引用、无效上限或关闭地点拒绝新运输且不扣任何资源。
14. 出发后修改或关闭内容、停机恢复后结算仍使用原货物、报酬、名望键/上限、延误与灵骑快照。已有名望高于冻结上限时保持原值并显示增量为零，历史开始/结算请求不占新次数或重复发放。
15. 名望、路线状态与 operation 三阶段故障均回滚灵石、目的地、名望、灵骑状态/经验和路线结果；开始时已锁的货物与体力保持出发后状态。同请求重试成功，重复结算或并发结算不得重复发放，不同路线/货物输入返回冲突。
16. QQ 官方与 OneBot V11 的真实事件都能依次创建角色、寻仙、预览/开始运输、抵达和结算，数据库、operation 与玩家实际所得一致；文案不显示稳定键、请求编号或开发状态。
17. 公共项目物化时冻结名称、说明、需求、贡献资源、奖励、名望地点/上限、服务来源和成效文案；结算必须使用该快照。物品、灵石、地方名望和行旅声望经共享角色奖励事务发放，封顶后以实际所得记录并展示；坏 JSON 和名望、领奖记录、operation 写入故障均回滚，原请求可重试。
18. 公共项目内容变更或关闭后，旧项目仍按物化快照结算和重放，新项目才读取当前内容；不同输入重用 operation 必须冲突。QQ 官方与 OneBot V11 的真实命令链均覆盖内容变化、恢复、故障回滚和中文玩家文案，展示不泄露稳定键、成效键或内部状态。
19. 服务订单的名称、准入、成本、报酬、交付物、失败返还、地点要求、次数和期限均从生活内容读取；发布时锁定报酬和完整快照，接取与结算不重新解析当前服务定义。
20. 成功结算按冻结快照发放承接报酬和委托人交付物；失败返还冻结的委托人报酬比例、承接者材料和体力。过期接取会原子退款并记录 operation，重复请求只返回同一过期结果。
21. 损坏服务快照、资产/数值写入或账本写入故障都不得留下半笔订单或半笔奖励；解除故障后原 operation 可重试，停机重启后不重复发放。
22. QQ 官方与 OneBot V11 的发布、接取、过期退款和成功/失败结算均调用同一 application/repository；玩家文案只显示中文服务名称、订单状态和实际所得，不显示稳定键、operation 或开发状态。
