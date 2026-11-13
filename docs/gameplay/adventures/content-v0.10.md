# v0.10 贸易口秘境（魔渊契约集市与三界货栈）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.10`，
`rule_version=adventures-0.10.0`。本版只做内容扩展：给两个已开放但此前**没有任何活动**的贸易端点
补上通用秘境入口，并各加一名同地点敌人。不改通用秘境引擎、命令、表结构、目标口径、快照/事务/
幂等/恢复语义，也不新增物品。

## 1. 背景与选点

`demon.abyss_market`（魔渊集市）与 `beast.three_realms_trade_port`（三界贸易口）都是 `status: open`
的活跃贸易端点：前者登记 `economy.trade.xuantian_to_demon` 与 `production.demon_contract`，后者登记
`economy.trade.three_realms`；两处各有 `local_reputation_maximum=1000` 与 `codex.place.*` 地点图鉴。
但两处的秘境数为零，是当时唯一「已开放却没有任何秘境活动」的两处端点（其余无活动地点是青石镇
枢纽与宗门山门）。本版在此补上入口，让这两处端点具备可进入的通用秘境，并把掉落接回既有材料与
地方名望。

## 2. 新增通用秘境

`data/冒险/秘境.json`（kind `secret_realm`，`record_type: common`）追加 2 条记录：

| 秘境 | `key` | 别名（`进入秘境 <别名>`） | 地点 | 境界门 | 体力 | 路线 | 敌人 | 周限 |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| 魔渊契约集市 | `instance.secret_realm.abyss_market_run` | 魔渊集市秘境 | `demon.abyss_market` | 元婴 L1 | 20 | 资源→遭遇→选择 | `enemy.abyss_market_warden` | 2 |
| 三界货栈 | `instance.secret_realm.trade_port_convoy` | 贸易口秘境 | `beast.three_realms_trade_port` | 元婴 L1 | 20 | 资源→遭遇→选择 | `enemy.trade_port_smuggler` | 2 |

两条记录均为无凭证（`ticket_key: null` + `ticket_quantity: 0`），`expiry_seconds: 3600`，
`quota_period: week`、`quota_limit: 2`，`reputation_key` 与其地方名望奖励一致。

奖励：

| 秘境 | `first_reward` | `repeat_reward_pool` |
|:--|:--|:--|
| 魔渊契约集市 | `item.demon_core`×2 + `local.demon.abyss_market`×8 | 权重 2: 魔核×1；权重 1: 无奖励 |
| 三界货栈 | `item.beast_blood`×2 + `local.beast.three_realms_trade_port`×8 | 权重 2: 兽血×1；权重 1: 无奖励 |

两份奖励键都是既有闭合内容：`item.demon_core` 与 `item.beast_blood` 均为 `heaven` 品质材料、
已在 `data/物品`（材料）登记并有 `source.item.three_realms_materials` 来源；两个 `local.*` 名望键分别
指向本秘境所在地点。本版不新增物品、不新增奖池。

## 3. 新增敌人与发现

`data/战斗/敌人.json`（kind `enemy`）追加 2 条 `status: active` 记录，沿用既有元婴同阶兄弟记录
（`enemy.demon_ruins_scout`）的属性/技能/掉落档案形态，`location_key` 与对应秘境地点一致，
`stats.agility` 齐备，`combat_profile.random_pool_key` 唯一，掉落走既有 `reward_pool.enemy.three_realms`：

- `enemy.abyss_market_warden`（集市契约守卫，`demon.abyss_market`，hp 560 / attack 48 / 技能 `enemy_skill.blade_wave`）
- `enemy.trade_port_smuggler`（货栈私贩，`beast.three_realms_trade_port`，hp 540 / attack 46 / 技能 `enemy_skill.blade_wave`）

可发现性：在 `data/地图/地点.json` 的两处端点 `actions` 列表各追加对应秘境键
（`instance.secret_realm.abyss_market_run` / `instance.secret_realm.trade_port_convoy`），使地点把该活动
展示给玩家；`秘境预览` 与 `修仙帮助 探索` 的秘境列表由 `secret_realm_definitions` 数据驱动，自动
收录两条新记录，无需新增命令或帮助段。

## 4. 不做的事（刻意边界）

- 通用秘境引擎不读遭遇池：单敌人路线由记录自身的 `enemy_key` 驱动，`encounter_pool` 对本类秘境
  无消费者。因此本版**不**新增遭遇池，避免留下「有记录但无消费者」的悬空内容；敌人直接由
  `enemy_key` 引用并在验载期解析。
- 不新增主动地点门槛：秘境地点沿用两处端点既有的 `nascent_soul` L1 与阵营声望 ≥200 准入，本版
  不放宽、不收紧世界准入。
- 不改 `秘境预览`/`进入秘境`/`选择秘境节点`/`结算秘境` 的任何语义，也不改悬赏、图鉴里程碑、
  故事分支等其他域。

## 5. 验收

`test/test_trade_endpoint_realms.py` 覆盖：

- 两条记录按通用秘境合同逐字段核对（键前缀、`record_type`、地点、境界门、体力、无凭证、
  节点顺序、敌人、首/重奖励、周限、过期、名望键与奖励一致），别名解析；
- 发现性：两个地点 `actions` 含对应秘境键且 `codex_entry_key` 未变，两名敌人的 `location_key`/
  `combat_profile`/`stats.agility` 可解析；
- 预览在 `qq.official` 与 `onebot.v11` 两端列出两条记录及其节点/体力/周限/首奖励；
- 四类入场拒绝（地点不符、境界不足、体力不足、未进入先选节点），且拒绝不扣体力；
- 完整通关（进入→资源→遭遇→结算→选择→结算）发首通奖励、同 operation 回放同一战斗、
  重复结算幂等；二次通关走重复奖池；同周第三次返回 `SECRET_REALM_QUOTA_EXHAUSTED`；
- 三界货栈完整通关经真实战斗结算，`battle_sessions` 恰一行且敌人来自该秘境；
- 战斗失败（无武器）结算 `reward == {}` 且不发首通；超时结算 `outcome=expired` 且退还体力 20。

相关回归覆盖通用秘境预览、敌人档案、遭遇引用和内容完整性。

种子迁移：`冒险/秘境.json`、`战斗/敌人.json`、`地图/地点.json` 三份官方种子在
`scripts/seed_migrations.json` 中登记本版 `new_sha256`/`new_commit`，并把上一版 `new_sha256` 追加为
`old_sha256`（累积），旧官方 blob 或自定义宿主仍可迁移/保留。
