# Changelog

## 0.1.20

### Fixed

- 悬赏覆盖十个开放境界，补齐公开来源与指路：凡人铁石、跨境界云灵茶、运输服务、合道余料交付与专用天劫胜场。
- 悬赏日榜按配置权重无放回选择，过滤用尽日限与不可再取得的试炼目标；保留旧目标、奖励及周项目快照。
- 三份官方种子登记真实 Git 来源与迁移指纹，升级保留未知/自定义 JSON；质量检查覆盖 develop 推送。

## 0.1.19

### Added

- 元婴混元收束：`chapter.13.stage.1`–`.3`（入山问脉、循血猎兽、守山定契）补上 `layer_max=10`
  却一直没有主线的混元 L10，三关元婴 L10、`keep_running` 重试，末关 `next_stage_key` 为空；
  `chapter.12.stage.3` 改为链接 13.1，三键登记进 `_VERTICAL_SLICE_STAGES`。
  目标分别是抵达 `beast.ten_thousand_hills`、`explore.beast_hunt` 结算取得 `item.beast_blood`、
  以及该模式的遭遇战胜利。万兽山入口需妖界声望 200 或 `access.beast_ten_thousand_hills`，
  `desc`/`retry` 明写「近郊探索 → 阅读妖界史 → 完成妖界引导」与云舟渡口路线，不把入口说成可直达。
- 敌人内容化：`enemy.iron_boar`、`enemy.beast_guardian`、`enemy.tribulation_heaven` 补齐
  `combat_profile`，内容里写的 `stats` 此前被静默忽略（`enemy_definition` 回落到代码表）；
  战斗数值一字未改。现在 62 条敌人中 50 条由内容持有，18 条 `enemy.void_spire.*` 由塔内容解析。
- 内容完整性合同：`test/test_content_completeness.py` 校验「探索模式 → 地点 action → 遭遇池 →
  奖励池 → 境界门槛」五段链，外加主线目标可支付性、敌人来源闭合、模式/地点元数据与状态面。
- 装备目录完整性合同：`test/test_equipment_catalog.py` 校验 1866 条装备的槽位与 key 前缀、
  道途、成长档案、词条属性名（取自 `stats/rules.py` 自身表）、境界门槛，以及 12 个矩阵家族
  各 144 条与统一的成长档位分布。
- 聚气段指路引导：`guide.qi_gathering_breath`（命令 `聚气`）与 `guide.qi_gathering_ascent`
  （命令 `登阶`）补上此前主线、任务、引导三者皆空的聚气段；正文引用的修为阈值与
  `cross_realm_total_cultivation 4260` 由测试逐项对照 `境界.json`，防止文案漂移。

## Unreleased

### Added

- 元婴主线补全：`chapter.10.stage.1`–`chapter.12.stage.3` 九关（云城问舟、渡口候船、云舟北渡、
  入门问契、契阁残页、遗迹守卫、门备材料、归舟回城、回镇结卷）把 `chapter.9.stage.3` 接到
  魔渊入口、堕落遗迹与归途。目标为真实抵达（含云舟抵达 `demon.abyss_gate`）、
  `explore.demon_abyss` 的契约线索结算产物与遭遇战胜利、`explore.demon_threshold` 的魔核；
  九关元婴 L1–L9、`keep_running` 重试、末关结束链路，并登记进 `_VERTICAL_SLICE_STAGES`
  由既有 gate 校验正文长度、章节连续与 `state_changes`。`travel_arrival` 同时接受已抵达的
  `cloud_boat_sessions` 行。
- 灵田谷物链：`crop.cloud_rice` 改以 `item.grain.cloud_rice` ×1 作种（原为灵叶×2），
  播种 1 份收 4 份稻谷 + 1 份灵叶。
- 灵田多居所作物：作物定义收集全部 `residence_key` 前置，任一声明的居所即可播种；
  `crop.spirit_leaf` 同时声明 `residence.courtyard` 与 `residence.herb_court`，灵圃小院第二垄可种灵叶，
  未声明居所与城镇客房仍按原规则拒绝。
- Arena weekly ladder: `竞技场赛季` / `领取竞技场赛季奖励` (aliases `竞技场周榜` / `领取周榜奖励`)
  rebuild each closed week's board from immutable `arena_matches` history, freeze the top ranks
  into `arena_season_settlements` on first claim, and pay once per player per week from that frozen
  row. `players.arena_rating` / `arena_wins` never feed a settled week, later matches and player
  edits cannot move it, a per-match result still pays nothing, and the seven-day claim window leaves
  an expired week as a display record.
- Enemy declared skills actually shape a fight: shield/absorb/status effects are parsed, frozen into
  the battle snapshot and resolved by the turn engine; unknown effect types fail at content load.
- Exploration modes `explore.spirit_field_tending` and `explore.cloud_city_escort` are now listed by
  their own places, with seed-migration provenance for the edited location seed.
- Tribulation `automatic_phase_selection` is read from the runtime content pack and frozen into the
  trial snapshot; the breakthrough permit and its payout are parsed from quest content instead of
  hard-coded item/quest keys.

- P0/P1 implementation plan covering dependencies, acceptance commands and rollback points.
- Minimal standard-library runtime package with typed configuration and data-root boundaries.
- Side-effect-free composition root, lifecycle state, feature manifest registry and health report.
- Unified `Result`, `Error` and `OperationRecord` contracts plus deterministic Clock/Random/ID ports.
- Isolated unit-test foundation for the empty runtime; no gameplay or legacy implementation copied.
- Verified 12 isolated tests, compilation, editable installation, and local readiness CLI.
- Corrected the reference-baseline procedure to require a separate clean `main` clone;
  the clone was attempted twice but blocked by GitHub network/TLS failure, so the dirty
  legacy workspace was not read or used as evidence.
- P2 foundation: SQLite schema migration, transactional Unit of Work, and persistent
  operation ledger with replay, conflict, terminal-state, and rollback guarantees.
- P2 backup slice: SQLite online snapshots, SHA-256/schema metadata, integrity checks,
  pre-restore snapshots, path boundaries, and atomic restore.
- P2 adapter/security contracts: normalized OneBot/QQ scenes, ReplyPlan capability
  degradation, request deduplication, three-level rate limiting, Web envelopes,
  sessions, CSRF, permissions, idempotency-key checks, and safe file resolution.
- New-game product documentation: a decomposed design index, three-realm world model,
  public progression, six paths, alchemy/artifice/formation professions, versioned
  v0.1-v0.6 content packages, and an explicit legacy-reference boundary.
- `docs/foundation/player/content-v0.1.md`: stable onboarding state machine, fixed
  qualification range and adjustment rule, first-release rewards, guide gates, path/
  subprofession selection, operation semantics, acceptance cases, and rollback plan.
- `docs/implementation-plan.md`: new-game P0-P8 sequencing, vertical-slice scope,
  acceptance criteria, risk controls, and rollback points.
- All 91 `content-v0.1.md` through `content-v0.6.md` files now define actionable
  release content: typed stable IDs, prerequisites, costs, outputs, deterministic
  pools/snapshots, caps, failure paths, idempotency, permissions, observability,
  close/rollback handling, and cross-domain producer/consumer closure.
- `scripts/validate_content_docs.py`: repeatable content-document validator for
  version headers, release gates, links, key contracts, task reachability, endgame
  threshold closure, monotonic social caps, and legacy-reference isolation.
- `docs/foundation/progression/layers.md`: canonical ten-layer progression rules:
  L1–L3 entry, L4–L6 stable, L7–L9 perfect, L10 hunyuan; only L10 starts a
  cross-realm breakthrough, and historical three-stage data requires explicit migration.
- `docs/gameplay/livelihood/`: v0.1–v0.6 evergreen play loops for residences,
  plots, town commissions, service orders, trade routes, local reputation, public
  projects, and later realm/void/dao services. Their settlement contract forbids
  direct cultivation, breakthrough-readiness, combat-stat, or endgame-asset rewards.
- Added v0.1–v0.6 content packages for the requested core systems, with
  cultivation-style terminology: `routine/` (道历问安、补录道历、灵木聚财、道契、
  机缘寻宝、问道行卷、道号、功业录、七日入道、机缘密令), `adventures/`
  (悬赏榜、秘境试炼、主线道途、斗法留影), `foundation/advancement/`
  (闭关修行、道脉天书、体质根性、神通参悟、法器祭炼、灵纹重铸), and
  `companions/` (灵兽、灵骑、升级、蜕变、灵具与鞍具)。

### Changed

- Gameplay implementation is paused at the documentation baseline. Existing exploratory
  P3 player-registration code is not accepted as release behavior until rewritten against
  the `new_user -> mortal -> seeker -> cultivator` v0.1 contract.
- The test strategy now requires local Markdown-link, content-key, reference-boundary,
  and diff validation for every gameplay-document or content-package change.
- The product scope now excludes entertainment: media, WebDAV, third-party accounts,
  anime, minigames, and entertainment points have no documentation, content package,
  release placeholder, or implementation target in xiuxian3.
- The content validator now enforces 121 versioned content files and checks the
  four new feature domains, their stable IDs, v0.1/v0.6 boundaries, and endgame
  asset isolation.

### Not included

- No released player onboarding, cultivation, inventory, combat, production, market,
  NoneBot command, or Web gameplay exists yet. P0-P2 code is infrastructure exploration;
  P3 code must be reconciled to the new product baseline before it can be enabled.
