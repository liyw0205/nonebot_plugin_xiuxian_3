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

升级经验只能来自训练/灵粮/规定内容事件；重复喂养 operation 不重复消耗。喂养与蜕变材料成本只可从扣除市集、求购、拍卖预留后的可用背包数量中支出；可交易灵材已锁定时，操作必须拒绝且不得留下灵兽状态或 operation 写入。蜕变开始时冻结品种、等级、亲和、材料和随机池；失败保留原阶段并按表扣成本/进入冷却。灵兽/灵骑死亡不永久销毁，按伤势进入休养；终局和赛季关闭保留实体历史。

结缘 operation 保存首次结缘的实体结果。相同请求恢复时先核对原 operation 并回放该结果；只有新请求才按当前内容检查品种开放状态和来源。内容关闭不改变已结缘实体，也不妨碍已成功请求恢复。

装备变化写独立 operation，先锁唯一实例再结算；耐久为 0 只失效不丢失。灵兽战斗日志只记录快照引用，不把隐藏技能或所有者私密资料暴露给对手。

小型行囊与竹鹿鞍具的 `source_recipe_key` 分别指向个人生产配方
`recipe.companion.sack_small`、`recipe.companion.bamboo_saddle`；生产领取先收入背包，装备时
同事务扣背包并创建唯一灵具实例。本人公开领取主线首关会记录
`story.mainline.xuantian:chapter.1.stage.1`，作为竹鹿与木鼠的准确剧情来源；不把测试插入的事件当来源。
首只结缘灵兽按原规则出战。出战且可用、耐久大于零的行囊增加负重 5，进入属性/探索快照；
摆摊购买与求购交付在原正容量上限上加此值，容量为 0 的既有不限容量语义不变。
探索没有新增强制背包容量限制。鞍具按原运输快照减少灵骑体力消耗 1，最低 1。

短途运输会在同一事务中校验出行槽、可用状态、耐力和鞍具，冻结灵骑与路线快照并将状态置为 `travelling`。抵达结算恢复为 `available`，按内容包增加运输经验；运输险象使用开始 operation 的冻结种子判定，命中后转为 `injured` 并记录 `injury_until`，不得继续运输、装备或蜕变，休养完成后才可再次行动。
