# 社交域：用例、权限与验收

## 用例

`create_sect`、`apply_sect`、`review_member`、`contribute_sect`、`change_role`、`leave_sect`、
`invite_mentor`、`accept_mentor`、`reject_mentor`、`graduate_apprentice`、
`create_party`、`invite_party`、`accept_party`、`reject_party`、`confirm_party`、`leave_party`、
`get_party`、`start_service_order`、`deliver_service`。

当前开放的队伍为 `party.exploration_pair`：最多两人、创建时冻结地点、五分钟双方确认窗口，
队长退出时转移给仍在线的成员，否则队伍解散。该切片只产生队伍状态，不创建探索或战斗会话，
每次写操作均使用 operation ledger 幂等回放。

当前开放的师徒关系要求师傅筑基 L4、徒弟处于凡人至聚气 L6；邀请 24 小时过期，接受后为
`active`。徒弟完成入道、达到聚气 L3 并完成一次生产或常驻经营服务后，师傅可办理一次毕业，
结算地方名望、贡献和双方服务信誉，不直接发放修为或突破资源。

## 错误码

`SECT_NOT_FOUND`、`SECT_FULL`、`ALREADY_MEMBER`、`APPLICATION_EXISTS`、`SECT_PERMISSION_DENIED`、`SECT_ASSET_LOCKED`、`ROLE_CHANGE_INVALID`、`MENTOR_REQUIREMENT_MISSING`、`APPRENTICE_RELATION_CONFLICT`、`MENTOR_INVITATION_NOT_FOUND`、`MENTOR_INVITATION_EXPIRED`、`MENTOR_GRADUATION_NOT_READY`、`MENTOR_STATE_CONFLICT`、`PARTY_NOT_FOUND`、`PARTY_ALREADY_MEMBER`、`PARTY_MEMBER_CAP`、`PARTY_PERMISSION_DENIED`、`PARTY_INVITATION_NOT_FOUND`、`PARTY_LOCATION_MISMATCH`、`PARTY_CONFIRMATION_EXPIRED`、`PARTY_STATE_CONFLICT`、`SERVICE_ORDER_CONFLICT`。

## 验收

非管理职位不能改仓库；申请不能重复接受；队伍条件按全员检查，确认超时整体失效且不创建战斗；
队长退出不能留下不可结算队伍；服务失败按约定退款/赔偿；宗门贡献重试只增加一次。
