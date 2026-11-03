# v0.7 事件内容基线：飞升日

`docs/gameplay/events/content-v0.6.md` 把 `event.ascension_day` 定义为「赛季后 24h；展示结局、
新篇章入口；仅展示，不再改资产」，但仓内没有对应数据、规则、命令或测试。本版把它做成一个
**纯投影**事件：只读、无资产写入、无事务副作用。

## 数据合同

`data/事件/飞升日.json`（kind `ascension_day`）：

| 字段 | 值 | 说明 |
|:--|:--|:--|
| `window_hours` | 24 | 赛季 `ends_at` 起算的展示窗口 |
| `display_boards` | `ascension`、`dao`、`cooperation` | 必须落在 `season.final_heaven` 已发布的三榜键内 |
| `chapter_entry_keys` | `lane.builder|witness|traveler.chapter.01` | 必须引用已存在的 `mainline` 记录 |
| `require_frozen_season` | true | 只认 `final_heaven_seasons.status == 'frozen'` |
| `allow_assets` | **必须为 false** | 加载器强校验；写成 true 直接拒绝加载 |

数据只描述展示口径与窗口长度。结局取自 `endgame_endings`，名次取自赛季冻结快照
（`{"boards": {board: [{rank, anonymous_label, score, achieved_at}]}}`），本模块不重复存数。

## 校验与迁移边界

`events/ascension_day_content.py` 校验：kind 与键、字段集合、`window_hours` 1–168、
`allow_assets` 必须为 `false`、`require_frozen_season` 必须为 `true`、榜单键必须是三榜子集且不重复、
章节入口必须引用已登记 `mainline` 且不重复、别名非空；非法抛 `ContentError` 并在导入期构建，
部署校验同样失败。本事件**不新增表**：它是读取投影，旧库无需迁移。

## 运行时

- 窗口：`[season.ends_at, season.ends_at + window_hours)`，半开区间；起点即可见，闭合时刻即不可见。
- 状态：`pending`（尚未开始或无冻结赛季）、`open`（窗口内）、`closed`（窗口结束）。
  只有 `open` 公布榜单；`pending` 与 `closed` 只给状态与新篇章入口，避免窗口外继续展示过期名次。
- 读取：取最近一个 `frozen` 赛季 → 计算窗口 → 读本角色 `endgame_endings` → 读冻结榜单 →
  投影。读取使用 `writable=False`，**不写 `operations`**、不改任何资产、不写 `endgame_endings`。

## 命令与呈现

`飞升日`（别名 `飞升之日`、`新篇章`）。状态码 `ASCENSION_DAY_OPEN`、
`ASCENSION_DAY_PENDING`、`ASCENSION_DAY_CLOSED`、`ASCENSION_DAY_NO_SEASON`；
错误 `INVALID_ASCENSION_DAY_COMMAND`、`PLAYER_NOT_FOUND`、`REPOSITORY_BUSY`。

页面给出赛季号、落幕时间、窗口止点、本人结局标签、三榜名次与新篇章入口（`主线道途` 蓝字）。
展示页**不挂任何写操作按钮**；QQ 原生 Markdown 直接渲染，OneBot/纯文本降级为可读文本且不暴露稳定键。
`修仙帮助 探索` 追加飞升日段。

## 非目标

不改赛季排期、三榜计分与领取窗口；不写 `ending_state`；不新增新篇章内容本体（只列出既有入口）；
不提供任何「补领」「重看改写」类写入口。
