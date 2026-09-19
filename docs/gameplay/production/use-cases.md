# 生产域：用例与验收

## 用例

`preview_recipe`、`start_production`、`complete_production`、`deliver_production`、`cancel_production`、`collect_farm`。

## 错误码

`RECIPE_NOT_FOUND`、`REQUIREMENT_MISSING`、`MATERIAL_INSUFFICIENT`、`ENERGY_INSUFFICIENT`、`TOOL_BUSY`、`PRODUCTION_BUSY`、`ORDER_EXPIRED`、`DELIVERY_INVALID`。

## 验收

预览不扣资源；生产重试只锁一次材料；委托交付前产物不可被他人使用；过期不能同时完成；规则更新不重算进行中订单。