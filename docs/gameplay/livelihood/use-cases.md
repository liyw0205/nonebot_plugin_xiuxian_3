# 常驻经营域：用例与验收

## 用例

- `livelihood.lease_residence` / `livelihood.renew_residence` / `livelihood.rest`
- `livelihood.plant` / `livelihood.maintain_plot` / `livelihood.harvest`
- `livelihood.list_commissions` / `livelihood.accept_commission` / `livelihood.deliver_commission`
- `livelihood.publish_service` / `livelihood.accept_service` / `livelihood.settle_service`
- `livelihood.preview_route` / `livelihood.start_route` / `livelihood.settle_route`
- `livelihood.contribute_project` / `livelihood.settle_project`
- `livelihood.get_profile`

## 错误码

`RESIDENCE_REQUIRED`、`RESIDENCE_RENT_DUE`、`PLOT_NOT_READY`、`PLOT_MAINTENANCE_MISSED`、`COMMISSION_STOCK_EXHAUSTED`、`COMMISSION_ALREADY_ACCEPTED`、`SERVICE_REPUTATION_INSUFFICIENT`、`SERVICE_ESCROW_CONFLICT`、`ROUTE_QUOTA_EXHAUSTED`、`ROUTE_CARGO_LOCKED`、`LOCAL_REPUTATION_INSUFFICIENT`、`LIVELIHOOD_CONTENT_CLOSED`。

## 验收

1. 凡人可在不拥有修为/境界层数的情况下租居所、接城镇委托、种植和运输。
2. 种植、运输和服务订单不直接增加 `realm_cultivation` 或 `total_cultivation`。
3. 同一地块/委托库存/货物在并发请求下只被锁定一次。
4. 维护逾期、订单过期和路线失败按快照结算/释放，不双扣、不双返。
5. 名望和信誉改变只解锁服务槽、折扣、委托类型或公共建设参与，不增加伤害、突破率或境界层数。
6. 文本、按钮和 Web 入口都调用同一 application DTO；渲染失败不改变订单、地块或资产。