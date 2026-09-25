# 生产域：模型

`RecipeDefinition`：配方键、输入、工具、境界/地点/主道途/辅修条件、精力、时间、基础熟练度、质量阈值、失败表、产出表及 `content_version` / `rule_version`。个人订单保存配方结果定义和玩家准入快照，规则升级不重算旧订单；阵堂地点的宗门成员/教学邀请权限在预览和开始时都重新校验。

`ProductionOrder`：订单 ID、委托人、生产者、配方、输入锁定、目标品质、报价、状态、时间、结果快照和 operation ID。职业大师作品使用同一普通个人订单实体，不创建第二套物资扣除或结算机制。

`GatheringNode` 详见 `../exploration/model.md`；灵田记录地块、作物、种植时间、成熟时间、灵气、阵法修正和收取 operation。

`ProductionFacilitySlot`：稳定槽位键、洞天地点、设施类型、槽位序号、个人/宗门所有者、`unclaimed/active/inactive`、最近维护业务日和更新时间。`ProductionOrder.facility_slot_id` 保存订单占用的设施快照，数据库部分唯一索引保证同一槽位最多一个 `processing` 订单。
