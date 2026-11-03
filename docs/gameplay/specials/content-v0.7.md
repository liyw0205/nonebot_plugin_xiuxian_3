# v0.7 特色玩法内容基线：终局天榜

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`，`rule_version=specials-0.7.0`。
本版把 world v0.6 冻结、扩展内容 v0.6 登记的终局地点 `location.final_arena` 从「只有标签与地点行」
接入运行时：此前只有 `player/rules.py` 的展示名，没有地点记录、通路、轮次、敌人、用例或持久化。

## 1. 数据合同

- 新增 `data/特殊/终局天榜.json`（kind `final_arena`，已登记 `data/内容清单.json`）：
  - `arena.final_heaven.defaults`：`location_key: location.final_arena`、
    `schedule = {kind: utc_block, block_hours: 4, duration_seconds: 7200, claim_window_seconds: 86400}`、
    `attempt_limit_per_round: 3`、`stamina_cost: 15`、`required_realm: tribulation`、`required_layer: 6`。
  - `tier.final_arena.1|2|3`：中文标签「天榜初阶/天榜中阶/天榜上阶」，各自绑定一个该地点敌人
    `enemy.final_arena_guardian_1|2|3`，`required_best_tier` 为 0/1/2（连续阶梯），
    上阶声明 `title_key: title.final_arena.summit`，并给出中文别名（初阶/一阶、中阶/二阶、上阶/三阶）。
- 改动 `data/地图/地点.json`：新增 `location.final_arena`（世界「终局」、`status: open`、
  `requirements: [{type: realm, realm_key: tribulation, min_layer: 6}]`、`environment.risk: high`、
  `actions: [final_arena.challenge]`、`codex_entry_key: codex.place.final_arena`）。
- 改动 `data/地图/区域.json`：`region.tribulation.sky` 增加该地点成员与**双向**两条边
  `tribulation.sky_terrace ↔ location.final_arena`，`duration_seconds: 900`、`stamina: 15`，
  双方都带渡劫 L6 境界要求，且不挂凭证物品与每日次数（避免让飞升路成为进入跳板）。
- 改动 `data/图鉴/条目.json`：新增 `codex.place.final_arena`（分类 `place`，抵达即登记）。
- 改动 `data/战斗/敌人.json`：新增三条同地点敌人（含 `combat_profile.random_pool_key` 与
  `stats.agility`），属性量级对齐既有渡劫档敌人。
- 改动 `data/道历/道号.json`：新增展示称号 `title.final_arena.summit`（终榜留名）。

## 2. 加载期校验

`specials/final_arena_content.py` 解析并校验：默认记录 `active`、`name`/`desc`/`label` 非空；
`location_key` 必须存在且为已开放地点；`required_realm/layer` 必须与该地点自身的境界要求**一致**；
`schedule` 必须为 `utc_block`，`24 % block_hours == 0`、时长为整小时且不超过该区块；
数值为正整数；梯级键以 `tier.` 开头且唯一、`required_best_tier` 必须从 0 起连续、
`enemy_key` 必须解析为已开放敌人、`title_key` 必须解析为已开放称号、别名非空且无跨记录冲突。
非法一律抛 `ContentError`，并在导入期构建 `DEFINITIONS`，使部署验载即失败。

## 3. 轮次、配额与资格

- 轮次为 UTC 四小时区块（00/04/08/12/16/20 起）；`duration_seconds = 7200` 表示每轮**前两小时**开放，
  因此确实存在窗口外时段。轮次标识为 `final_arena:YYYYMMDDHHMM`。
- 窗口外：普通移动在预览缺项中给出「天榜活动轮次」并拒绝启程（`EVENT_NOT_ACTIVE`，与既有战场同码）；
  挑战返回 `FINAL_ARENA_NOT_OPEN`。两者均零写、不扣体力。
- 每角色每轮次最多挑战 `attempt_limit_per_round = 3` 次；每次进入扣除 15 体力。
- 资格为渡劫 L6（与冻结地点行一致）；不满足时预览显示缺失项，挑战返回
  `FINAL_ARENA_LOCATION_REQUIRED`。

## 4. 战斗、结算与展示边界

- 挑战复用服务端权威自动战（`pve.final_arena`）：开始时冻结层级、敌人、轮次窗口、资格与体力成本，
  历史挑战不因内容改值而重算；启动失败整笔回滚并退还体力。
- 结算只推进该角色在本赛季的天榜最高层级、写入 `activity_events`（`final_arena.challenge`）
  与首通展示称号 `title.final_arena.summit`（上阶首通，称号路径幂等）。
- **不写** `endgame_status`、天劫债、道果进度、`ascension_merit`、灵石、修为与背包物品；
  失败只记录失败挑战，不扣资产。「不影响飞升资格」由此实现。
- 重启后可结算未完成挑战；同 operation 重放返回原结果，换输入返回 `LEDGER_CONFLICT`。

## 5. 入口、呈现与帮助

- `终局天榜 [层级]`（只读：轮次窗口、本轮已用/上限、本人最高层级与首通状态、三级可挑战状态）、
  `挑战天榜 <层级>`、`结算天榜`。
- QQ 原生 Markdown：列表页每级附 `挑战天榜 <中文名>` 蓝字预填；单项预览可挑战时只附一个
  「挑战此层级」按钮，结算成功后只附一个「再看终局天榜」按钮。
- OneBot/纯文本降级为可读命令与「可发送：…」，不保留 `command:`、不暴露 `tier.*`/`enemy.*` 稳定键。
- `修仙帮助 探索` 追加数据驱动的终局天榜段落（轮次、门槛、三级名称与蓝字预填，无按钮）。
- 错误码：`FINAL_ARENA_NOT_OPEN`、`FINAL_ARENA_LOCATION_REQUIRED`、`FINAL_ARENA_TIER_LOCKED`、
  `FINAL_ARENA_ATTEMPT_CAP`、`FINAL_ARENA_CHALLENGE_NOT_FOUND`、`INVALID_FINAL_ARENA_COMMAND`，
  以及复用的 `STAMINA_INSUFFICIENT`、`BATTLE_BUSY`、`BATTLE_COOLDOWN`，均零写。

## 6. 边界

不新增境界、道途、物品、奖池、配方；不做排行榜奖金、付费刷新、押注与掠夺；不开放跨服匹配、
跨服身份合并或玩家间资产转移；不改 `season.final_heaven` 三榜数值、称号键、领奖窗口与匿名展示；
不改战斗引擎的回合与自动行动契约。关闭天榜内容时列表与挑战按内容失败拒绝，已结算记录与称号不回退。
