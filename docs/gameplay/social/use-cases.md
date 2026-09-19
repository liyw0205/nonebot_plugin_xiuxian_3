# 社交域：用例、权限与验收

## 用例

`create_sect`、`apply_sect`、`review_member`、`contribute_sect`、`change_role`、`leave_sect`、`invite_party`、`accept_party`、`start_service_order`、`deliver_service`。

## 错误码

`SECT_NOT_FOUND`、`SECT_FULL`、`ALREADY_MEMBER`、`APPLICATION_EXISTS`、`SECT_PERMISSION_DENIED`、`SECT_ASSET_LOCKED`、`ROLE_CHANGE_INVALID`、`PARTY_MEMBER_INVALID`、`SERVICE_ORDER_CONFLICT`。

## 验收

非管理职位不能改仓库；申请不能重复接受；队伍条件按全员检查；服务失败按约定退款/赔偿；宗门贡献重试只增加一次。