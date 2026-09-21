# 修炼与构筑养成域：模型、状态机与用例

## 状态机

```text
retreat: preview -> running -> claimable -> settled | expired
constitution: unset -> selected -> reshaping -> selected
node: locked -> available -> learned -> maxed
skill: known -> training -> mastered
item_temper: preview -> locked -> resolved_success/failed
item_refine: preview -> locked -> resolved_success/failed
```

## 用例

- `progression.preview_retreat`、`progression.start_retreat`、`progression.settle_retreat`
- `constitution.select`、`constitution.reshape`
- `talent.unlock_node`、`talent.reset_tree`
- `skill.train`、`skill.promote`
- `item.tempering`、`item.refinement.preview`、`item.refinement.commit`

## 统一数值

- 闭关：默认每次 2–8 小时，每角色同时 1 次，最多结算 8 小时/业务日；离线时间超过 24 小时不继续累加。
- 技能等级、天赋节点、法器强化和洗练结果都以整数/bp 计算，成功与失败池在开始时固定。
- 失败保护必须写明保底计数/耐久/部分返还；同一 operation 重试不重新随机。
- 法器洗练前锁定实例，成功才替换词条；失败保留旧词条，最多扣除内容规定材料/耐久。

## 观测与回滚

记录修炼窗口、实际收益、来源 modifier、每日上限、节点/技能等级变化、强化等级、词条旧新摘要和失败保护。配置错误只能关闭新操作、保留已结算快照并用补偿 operation 修复，不能直接改历史结果。