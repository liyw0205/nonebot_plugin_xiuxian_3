# 生产域：模型

`RecipeDefinition`：配方键、输入、工具、境界/地点/主道途/辅修条件、精力、时间、质量阈值、失败表、产出表及 `content_version` / `rule_version`。个人订单保存配方结果定义和玩家准入快照，规则升级不重算旧订单。

`ProductionOrder`：订单 ID、委托人、生产者、配方、输入锁定、目标品质、报价、状态、时间、结果快照和 operation ID。职业大师作品使用同一普通个人订单实体，不创建第二套物资扣除或结算机制。

`GatheringNode` 详见 `../exploration/model.md`；灵田记录地块、作物、种植时间、成熟时间、灵气、阵法修正和收取 operation。
