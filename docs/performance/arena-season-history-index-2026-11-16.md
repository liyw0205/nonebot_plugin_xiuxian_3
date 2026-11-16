# Arena season history query performance

Date: 2026-11-16

Branch: `develop`

Baseline: `25b2940`
Runtime boundary: Linux install/runtime remains `/root/myenv`; this local
benchmark used `/home/nonebot-shared-venv/bin/python` only.

## Measured hotspot and change

The real read-only `竞技场赛季` dispatch selected seven narrow columns from
`arena_matches`, whose rows also contain large snapshot and result JSON. The
query filters by `settled_at`; `EXPLAIN QUERY PLAN` showed `SCAN arena_matches`.
The schema now creates `idx_arena_matches_settled_events`, a covering index
with `settled_at` as its range prefix. Existing databases receive it through
the normal idempotent schema initialization (`CREATE INDEX IF NOT EXISTS`);
the history table and match payloads are unchanged.

## Same-fixture comparison

Command used one deterministic 1,000-user / 1,000-match temporary SQLite
fixture, 60 actual `竞技场赛季` dispatches at concurrency 1/10/50, SQL tracing,
OneBot and QQ normalization, and two counterbalanced before/after rounds per
concurrency:

```text
flock -w 600 /tmp/nonebot-project-validation.lock bash -c 'ulimit -v 4194304; timeout 300s /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py --users 1000 --batch-size 250 --requests 60 --concurrency 1 10 50 --compare-arena-season-index --profile-sql --command "竞技场赛季"'
```

Every row below is `p50 / p95 / p99 ms`, with both repeats shown in execution
order.

| Concurrency | Before, repeat 1; repeat 2 | With index, repeat 1; repeat 2 |
| ---: | --- | --- |
| 1 | 16.488 / 48.518 / 65.310; 16.392 / 28.837 / 66.650 | 13.598 / 19.752 / 57.139; 13.547 / 14.422 / 55.100 |
| 10 | 612.890 / 763.583 / 804.881; 595.760 / 691.641 / 717.714 | 509.891 / 631.540 / 664.504; 464.698 / 543.705 / 609.992 |
| 50 | 1718.986 / 3676.453 / 3726.602; 1799.410 / 3712.165 / 3761.411 | 1617.473 / 3185.027 / 3228.188; 1294.198 / 2978.989 / 3034.324 |

Both repeats improved p95 and p99 at every concurrency. At concurrency 50,
p95 improved 13% and 20%, and p99 improved 13% and 19%. The query plan changed
to `SEARCH arena_matches USING COVERING INDEX idx_arena_matches_settled_events
(settled_at<?)`. SQL counts stayed at 360 per 60-request level (one cold c1
baseline round traced 361 while the connection was first opened). Errors were
zero for all 720 measured requests.

CPU seconds by concurrency were c1 `1.189/1.159 -> 0.961/0.904`, c10
`7.604/7.175 -> 6.169/5.680`, and c50 `7.777/8.052 -> 6.671/5.991`.
Process RSS high-water stayed within 119.629 MiB at c1 and 138.164 MiB at c10
and c50; it is a process-wide high-water, not an independent per-variant peak.
Executor queue p95 by repeat was c1 `0.102/0.094 -> 0.113/0.106ms`, c10
`536.358/531.061 -> 417.249/300.867ms`, and c50
`3151.858/3295.713 -> 2829.943/2638.632ms`. At c50 connection-open p95
remained `0.007/0.007ms` before and after, with eight workers observed. This
index reduces work queued behind the board path, but does not eliminate the
high-concurrency backlog.
The index occupied 61,440 bytes in the 1,000-match fixture and took 5.1-18.3ms
to build across the repeated toggles. This small-fixture build cost does not
claim a production-scale migration duration. The schema index was active while
the deterministic fixture was seeded, so seed time also includes index
maintenance; this comparison isolates query-time behavior, not insert cost.
Both variants used the same seed (`29,331,904` bytes before runtime close) and
the same SQLite file. After toggling was complete, the shared DB was restored
with the index and measured `15,900,672` bytes; this is not a per-variant file
size comparison. Both reports confirmed `temporary_database_cleaned: true`.

## Verification and limits

The shared-lock regression run covered the performance harness and season
settlement behavior. A restart test drops the new index from a populated
temporary database, reinitializes the repository, then verifies the match rows
are unchanged and the covering plan is restored. No 100k/1M fixture was used;
this change is limited to the measured season-history query. The executor
profile showed that c50 queue wait remains much larger than connection-open
time, so executor sizing or warmup is not inferred as a fix from this result.
