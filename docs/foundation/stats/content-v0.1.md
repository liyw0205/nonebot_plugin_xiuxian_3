# v0.1 属性内容基线：初始资质与感气数值

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.1`
- `rule_version`：`stats-0.1.0`
- 写用例：`player.start_seeking` 固定资质、`stats.freeze_snapshot` 冻结结算快照；`stats.preview` 只读。

## 1. 初始资质

寻仙问道生成六项基础属性。每项范围 5–15，合计必须恰为 60；任何不满足范围/总和的数据都返回 `STAT_VALUE_OUT_OF_RANGE`，不能自动截断后写入。

| `stat_key` | 展示名 | 初始范围 | 结算职责 |
|:--|:--|:--|:--|
| `body` | 体魄 | 5–15 | 气血、近战、负重 |
| `spirit` | 灵力 | 5–15 | 灵力上限、术法、护盾 |
| `insight` | 悟性 | 5–15 | 修炼、学习、生产学习 |
| `root` | 根骨 | 5–15 | 生命成长、突破准备、负面抗性 |
| `agility` | 身法 | 5–15 | 先手、闪避、探索效率 |
| `fortune` | 气运 | 5–15 | 事件质量、掉落波动 |

生成算法：每项先分配 5 点，将剩余 30 点按 `qualification.v0.1` 保存的确定性随机顺序逐点投放；单项达到 15 后跳过。玩家可通过 `player.swap_qualification_stats` 交换任意两项一次；交换不改变总和、随机池或原资质快照。不能重抽、加点或把气运转化为稳定伤害。

## 2. 派生属性公式

`realm_index`：凡人 0、感气 1、聚气 2、筑基 3。`realm_layer`：凡人 0，正式境界 1–10；段位不单独参与计算。运行时全部为整数；倍率使用 bp，`10000=100%`。中间乘法使用足够宽整数，最后统一向下取整。

```text
realm_growth = 20*realm_index + 3*max(realm_layer - 1, 0)
max_hp = 100 + realm_growth + 8*body + 5*root
max_mp = 60 + 18*realm_index + 2*max(realm_layer - 1, 0) + 10*spirit + 4*insight
carry_capacity = 20 + 2*body + 5*realm_index + floor(max(realm_layer - 1, 0) / 2)
initiative = 10 + agility
training_rate_bp = 10000 + 80*insight + 25*max(realm_layer - 1, 0)
exploration_rate_bp = 10000 + 50*agility + 15*max(realm_layer - 1, 0)
breakthrough_prepare_bp = 20*root
```

派生属性只引用冻结的 `StatSnapshot`；技能/装备/地点/状态分别作为 `path_bp`、`build_bp`、`environment_bp`、`temporary_bp` 乘区写入来源列表。最终值：`floor(base * (10000+path_bp) * (10000+build_bp) * (10000+environment_bp) * (10000+temporary_bp) / 10^16) + flat`。

## 3. 上限、软上限与状态

| 属性 | 常驻上限 | 临时总上限 | 特殊规则 |
|:--|--:|--:|:--|
| 单项增伤 | 3,500 bp | 8,000 bp | 超出部分截断并记录 `STAT_CAP_APPLIED` |
| 闪避/免伤/控制抵抗 | 7,500 bp | 8,500 bp | 不允许 100% 常驻无敌 |
| 修炼倍率 | 4,000 bp | 6,000 bp | 环境与状态乘区各自计算 |
| 探索发现率 | 3,000 bp | 5,000 bp | 只影响内容池权重，不保证稀有掉落 |
| 负重 | 无倍率上限 | 物品容量硬限制 | 超容量拒绝获得/移动，不丢物品 |

`weakness`：修炼 `temporary_bp=-2000`；`pollution`、血脉和道途状态不在本版本直接改基础六维，必须通过 `path_stats` 说明来源。所有负值先在所属乘区相加，再应用硬上限。

## 4. 快照、错误与验收

`StatSnapshot` 最少保存：`snapshot_id`、玩家、六维、`realm_key`、`realm_layer`、派生段位、道途、装备、地点、状态、派生值、来源列表、`stats-0.1.0`、创建时间与用途。快照不可变；更换装备/地点/状态只能创建新快照。

错误：`STAT_PLAYER_NOT_FOUND`、`STAT_SOURCE_MISSING`、`STAT_VALUE_OUT_OF_RANGE`、`STAT_CAP_APPLIED`（警告而非拒绝）、`STAT_SNAPSHOT_INVALID`。资料预览可显示最近有效快照并标记过期；任何资产结算不得使用无效快照。

验收：属性总和与边界正确；相同输入得到相同快照摘要；同来源不进入两个乘区；上限截断可解释；更换装备不修改旧快照；系统时间和浮点不会影响结果。