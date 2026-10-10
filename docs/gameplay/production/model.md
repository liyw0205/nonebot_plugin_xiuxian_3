# 生产域：模型

`RecipeDefinition`：配方键、输入、工具、境界/地点/主道途/辅修条件、精力、时间、基础熟练度、质量阈值、失败表和产出表。个人生产从 `data/生产/配方.json` 解析全部字段，不另维护 Python 数值表；记录另含展示 `desc`、开放 `status` 和命令 `aliases`。数量是资产键到正整数的对象，失败返还允许零且不能超过输入。物品、灵具、工具、境界、地点、道途、辅修及 `source_recipe_key` 均校验引用；坏内容拒绝新开，不静默补值。

个人订单保存配方结果定义、实际成本、质量因子和玩家准入快照，内容改名、改值或关闭不重算旧订单；稳定配方键的开始请求先回放 operation 再读取新内容。阵堂地点的宗门成员/教学邀请权限在预览和开始时都重新校验。

`ProductionOrder`：订单 ID、委托人、生产者、配方、输入锁定、目标品质、报价、状态、时间、结果快照和 operation ID。职业大师作品使用同一普通个人订单实体，不创建第二套物资扣除或结算机制。

`GatheringNode` 详见 `../exploration/model.md`；灵田记录地块、作物、种植时间、成熟时间、灵气、阵法修正和收取 operation。

`ProductionFacilitySlot`：稳定槽位键、洞天地点、设施类型、槽位序号、个人/宗门所有者、`unclaimed/active/inactive`、最近维护业务日和更新时间。`ProductionOrder.facility_slot_id` 保存订单占用的设施快照，数据库部分唯一索引保证同一槽位最多一个 `processing` 订单。
