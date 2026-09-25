# 生产域：用例与验收

## 用例

`preview_recipe`、`start_production`、`complete_production`、`deliver_production`、`cancel_production`、`collect_farm`、`production.claim_facility_slot`。

洞天二层的 `认领设施槽位 <灵田1|炼丹房|炼器台|阵基> [个人|宗门]` 将槽位绑定到所有者；每个槽位同时最多一个 `processing` 订单。维护 job 以 `slot_id + business_date` 幂等收取 100 灵石，余额不足只将设施设为 `inactive`，不取消已经 processing 的订单；订单完成、失败或过期恢复后释放槽位。

## 错误码

`RECIPE_NOT_FOUND`、`REQUIREMENT_MISSING`、`MATERIAL_INSUFFICIENT`、`ENERGY_INSUFFICIENT`、`TOOL_BUSY`、`PRODUCTION_BUSY`、`ORDER_EXPIRED`、`DELIVERY_INVALID`、`FACILITY_SLOT_OCCUPIED`、`FACILITY_SLOT_REQUIRED`、`FACILITY_MAINTENANCE_UNPAID`、`FACILITY_OWNER_INVALID`。

## 验收

预览不扣资源；生产重试只锁一次材料；委托交付前产物不可被他人使用；过期不能同时完成；规则更新不重算进行中订单。阵堂配方在阵堂地点必须重新校验宗门成员或教学邀请，不能仅凭已进入地点放行。职业作品需验证境界、主道途/辅修、材料不足零扣除、版本与质量快照、成功/失败、恢复和 operation 冲突；失败订单不能产出大师作品。辅修三艺必须分别完成三个个人生产订单才能合成，`交付合道作品` 只接受合成/对应主道途的真实背包产物并只消费一次。QQ 官方与 OneBot V11 适配器必须覆盖预览、开始、领取和作品交付的共享 application 流程。
