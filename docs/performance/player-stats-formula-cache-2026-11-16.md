# Player Status Formula Reuse

Date: 2026-11-16

Branch: `develop`

Baseline: `8a94138`

Runtime boundary: Linux install/runtime remains `/root/myenv`; the shared
interpreter is used only for local development, tests, and benchmarks.

## Measured hotspot and change

The real `我的状态` command recalculated the same content-derived stats formula
for every profile request. Each call copied and validated the formula record,
serialized its canonical form, and computed its SHA-256 fingerprint. The
100-user profile measured this stage at roughly `0.11ms` per request. The player
and stats reads used player-scoped indexes; equipment and companion reads also
used indexes, with small `ORDER BY` temporary B-trees. No full-table scan was
found.

The repository now reuses the immutable `StatsFormula` for the identity of its
current `ContentBundle`. Replacing the bundle invalidates the cached formula;
other `build_stat_preview()` callers retain the original uncached default.
Formula fingerprints and profile payloads remain identical.

## Same-fixture comparison

One deterministic temporary SQLite database contained 100 users, 100 arena
matches, and 100 domain-front rows. Its seed size was `7,663,144` bytes; after
runtime close, both variants reported `5,169,152` bytes. The same database was
used for four counterbalanced repeats of 60 actual `我的状态` dispatches at
concurrency 1/10/50 per variant. Requests exercised the OneBot and QQ
normalization paths; no live QQ account was used. Full repository profile
results were equal, SQL/query plans were unchanged, every request succeeded,
and the owned temporary directory was removed.

Each cell is the median across the four repeats, `p50 / p95 / p99 ms`:

| Concurrency | Uncached formula | Repository formula cache | Median CPU seconds, before -> after |
| ---: | --- | --- | --- |
| 1 | 1.502 / 1.628 / 1.799 | 1.388 / 1.507 / 1.643 | 0.097 -> 0.090 |
| 10 | 21.190 / 27.799 / 28.879 | 20.083 / 27.423 / 32.318 | 0.232 -> 0.231 |
| 50 | 65.709 / 140.361 / 143.280 | 63.249 / 142.177 / 146.053 | 0.249 -> 0.241 |

At concurrency 1, response median p50/p95/p99 improved by about 7.6%/7.4%/8.7%.
The c10 median p50/p95 improved modestly; p99 was noisy. The c50 median p50
improved, while p95/p99 were effectively unchanged within executor scheduling
variation and did not improve. One c10 cached round had an `81.127ms` p95,
including a `74.692ms` connection-open p95; one c50 cached round had a
`108.069ms` p50 with executor queue p95 at `136.074ms`. These are retained as
observed results, not attributed to formula evaluation. The change makes no
high-concurrency tail-latency claim.

Process RSS high-water was unchanged at `110.379MiB` for c1 and `116.543MiB`
for c10/c50. Connection counts stayed at 3/9/9. SQL remained 360 statements
per 60-request measured level (one cold c1 sample traced 361), confirming this
is not a query-count optimization. EXPLAIN used `idx_equipment_instances_equipped_slot`,
the constitution profile player index, `idx_companion_gear_player`, and the
companion primary key; the same plans appeared for both variants.

## Verification and limits

The concentrated shared-lock correctness run completed with `171 passed, 3
deselected` in 69.51 seconds. It covered player profile and stat contracts,
content-bundle cache invalidation, response behavior, and existing benchmark
contracts. The two top-N/formula comparison smoke tests were deferred from this
layer because each comparison ran once on its measured fixture. `py_compile`
and `git diff --check` passed. The full before/after comparison used 100 users;
no 1k/100k/1M fixture was run for this stage. CI for this change is pending.
