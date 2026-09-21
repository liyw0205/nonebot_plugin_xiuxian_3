# Changelog

## Unreleased

### Added

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