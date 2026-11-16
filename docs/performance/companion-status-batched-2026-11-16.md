# `灵兽状态` gear read batching

Date: 2026-11-16
Branch: `develop`
Scope: real OneBot text and QQ normalization/application dispatch; temporary
SQLite only. Linux runtime/install defaults remain `/root/myenv`.

## Evidence

The status path previously selected each companion's equipped gear separately.
On the deterministic fixture, `EXPLAIN QUERY PLAN` reported
`SCAN companion_gear_instances` for that per-companion query. The new path reads
all equipped gear for the player once and groups by companion; it uses the
existing `idx_companion_gear_player (player_id, status, created_at)` index:
`SEARCH companion_gear_instances USING INDEX idx_companion_gear_player
(player_id=? AND status=?)`.

Fixture and request population were identical for both variants. The fixture
contained 1,000 users, five active companions per user, and one equipped gear
row per companion. Seed and post-run database size were 29,331,904 bytes. Each
variant used two counterbalanced repetitions of 60 requests at concurrency 1,
10, and 50, with SQL tracing enabled. Both OneBot and QQ status requests were
included in the output-equivalence check.

| Concurrency | Variant | p50 ms (r1/r2) | p95 ms (r1/r2) | p99 ms (r1/r2) | CPU s (r1/r2) | RSS high-water MiB | SQL/request | gear SQL/request | Errors |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | before per-companion | 5.928 / 5.956 | 6.086 / 6.509 | 6.911 / 6.976 | 0.362 / 0.365 | 118.91 | 7 | 5 | 0 |
| 1 | after player batch | 4.224 / 4.217 | 4.736 / 4.477 | 5.703 / 4.624 | 0.262 / 0.259 | 118.91 | 3 | 1 | 0 |
| 10 | before per-companion | 77.078 / 78.172 | 84.625 / 86.122 | 85.690 / 87.514 | 0.789 / 0.777 | 133.316 | 7 | 5 | 0 |
| 10 | after player batch | 74.511 / 73.336 | 88.181 / 115.916 | 107.947 / 119.210 | 0.778 / 0.674 | 133.316 | 3 | 1 | 0 |
| 50 | before per-companion | 298.294 / 343.359 | 459.165 / 439.713 | 464.737 / 442.885 | 0.840 / 0.823 | 135.375 | 7 | 5 | 0 |
| 50 | after player batch | 309.178 / 289.070 | 416.135 / 418.595 | 419.279 / 422.118 | 0.694 / 0.693 | 135.375 | 3 | 1 | 0 |

Across the two repetitions, CPU fell from 3.956 s to 3.360 s (15.1%). At
concurrency 50, both after p95 samples and both p99 samples were below the
corresponding before samples. Output data/message/action contracts were
identical and all 720 requests completed without errors. The temporary
database directory was removed after the run.

The 100-user smoke comparison showed the same query reduction (`300 -> 60`
gear statements per 60-request level) and zero errors; the 1k fixture was used
only to make the full-table-scan cost visible. No 100k/1M fixture was created.

## Validation

The focused companion suite passed (`7 passed`) under
`flock -w 600 /tmp/nonebot-project-validation.lock`, the shared development
interpreter, `timeout`, and `ulimit -v 4194304`. The benchmark command used the
same lock and limits; its temporary fixture was cleaned. Existing Linux
installation/runtime configuration was not changed.
