# 灵兽与灵骑域：模型、状态机与用例

## 状态机

```text
beast: egg -> bonded -> active -> resting/injured -> retired
beast evolution: eligible -> preparing -> evolved/failed
mount: contract -> bonded -> available -> travelling -> resting
gear: unbound -> equipped -> locked -> unequipped/broken
```

## 用例

- `beast.hatch`、`beast.feed`、`beast.train`、`beast.evolve`
- `beast.equip_gear`、`beast.remove_gear`
- `mount.bond`、`mount.dispatch`、`mount.rest`
- `companion.claim_reward`、`companion.rename`

## 结算要求

升级经验只能来自训练/灵粮/规定内容事件；重复喂养 operation 不重复消耗。蜕变开始时冻结品种、等级、亲和、材料和随机池；失败保留原阶段并按表扣成本/进入冷却。灵兽/灵骑死亡不永久销毁，按伤势进入休养；终局和赛季关闭保留实体历史。

结缘 operation 保存首次结缘的实体结果。相同请求恢复时先核对原 operation 并回放该结果；只有新请求才按当前内容检查品种开放状态和来源。内容关闭不改变已结缘实体，也不妨碍已成功请求恢复。

装备变化写独立 operation，先锁唯一实例再结算；耐久为 0 只失效不丢失。灵兽战斗日志只记录快照引用，不把隐藏技能或所有者私密资料暴露给对手。

短途运输会在同一事务中校验出行槽、可用状态、耐力和鞍具，冻结灵骑与路线快照并将状态置为 `travelling`。抵达结算恢复为 `available`，按内容包增加运输经验；运输险象使用开始 operation 的冻结种子判定，命中后转为 `injured` 并记录 `injury_until`，不得继续运输、装备或蜕变，休养完成后才可再次行动。
