# 数据内容域：校验与发布

校验顺序：解析 schema -> 检查稳定键/版本 -> 建立引用图 -> 检查数值/权重/条件 -> fake 角色模拟 -> 生成报告。

规则发布生成 `RuleRelease`：版本、公式摘要、参数差异、影响玩法、经济影响、审批人和生效时间。

发布状态：`draft -> validated -> previewed -> approved -> active`；失败进入 `rejected`，旧 active 版本不变。