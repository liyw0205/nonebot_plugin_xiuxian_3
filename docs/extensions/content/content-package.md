# 数据内容域：内容包

内容包结构：`schema_version`、`content_version`、`rule_version`、生成时间和 definitions。

目录：`world/`、`progression/`、`paths/`、`skills/`、`items/`、`recipes/`、`quests/`、`events/`、`rewards/`、`livelihood/`。

稳定键使用字符串。内容定义引用地点、技能、物品、配方和奖励池时必须可解析，不能执行代码、SQL、模板或文件路径。