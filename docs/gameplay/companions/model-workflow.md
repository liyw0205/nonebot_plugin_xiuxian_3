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

装备变化写独立 operation，先锁唯一实例再结算；耐久为 0 只失效不丢失。灵兽战斗日志只记录快照引用，不把隐藏技能或所有者私密资料暴露给对手。