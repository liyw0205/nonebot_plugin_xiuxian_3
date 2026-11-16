# Idle preview shared-state performance

Date: 2026-11-16
Branch: `develop`
Baseline: `226d843`
Runtime boundary: Linux install/runtime remains `/root/myenv`; the local
benchmark used `/home/nonebot-shared-venv/bin/python` only.

## Measured Path

The real all-route `挂机预览` dispatch evaluated every route independently.
For each route it reread validated local reputation, checked active idle and
long-action state, and counted that route's daily settlements. The all-route
path now prepares the unchanged player state once, recognizes an active idle
assignment as satisfying the long-action lock predicate, and groups today's
settlement counts by requested route. Route-specific eligibility checks and
their message/presentation contracts are unchanged.

## Same-Fixture Comparison

One temporary 1,000-user SQLite fixture was reused by both variants. It
contained 2,000 deterministic daily-history rows (one `claimed` and one
`expired` row per player across two routes). Each variant ran 60 actual
`挂机预览` dispatches at concurrency 1/10/50, alternating OneBot and QQ
normalization, with SQL tracing and two counterbalanced repetitions per level:

```text
flock -w 600 /tmp/nonebot-project-validation.lock timeout 300s bash -c 'ulimit -v 4194304; /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py --users 1000 --batch-size 250 --requests 60 --concurrency 1 10 50 --command "挂机预览" --compare-idle-preview-state --profile-sql'
```

Each value is `p50 / p95 / p99 ms`; repeats are shown in execution order.

| Concurrency | Before: repeated route reads | After: shared request state |
| ---: | --- | --- |
| 1 | `16.510/17.794/25.574`; `16.418/17.369/19.099` | `12.760/15.809/18.919`; `12.757/14.237/17.806` |
| 10 | `468.474/531.181/537.148`; `466.666/530.436/537.662` | `233.946/282.506/292.691`; `226.869/278.433/281.884` |
| 50 | `1383.353/2862.586/2902.234`; `1401.247/2838.681/2878.029` | `692.550/1406.065/1444.100`; `678.999/1402.699/1450.539` |

All 720 measured requests returned without error, all preview records matched
field-for-field before and after, and both reports confirmed cleanup of the
temporary database. The seeded database was `29,331,904` bytes; the shared
post-run database was `16,965,632` bytes. Traced SQL fell from 19,560 per
60-request level to 840 (95.7% fewer statements). CPU seconds at c1/c10/c50
were `1.015/1.000`, `5.011/4.925`, `5.350/5.412` before and
`0.791/0.787`, `2.304/2.185`, `2.292/2.309` after. The process RSS high-water
was at most `130.84 MiB`; it is a process-wide high-water shared across
variants and is not presented as a per-variant memory reduction.

At c50 executor queue p95 fell from `2445.357/2374.286ms` to
`1194.171/1190.434ms`; eight workers were active in both variants. The active
idle lookup uses the existing covering player/status index. The grouped daily
count uses the existing player/status index and a small temporary B-tree for
`GROUP BY`; no index or schema change was added.

## Correctness and Limits

The focused shared-lock suite covers active idle/long-action messages, daily
route limits, location/reputation gates, malformed local-reputation JSON, the
real QQ/OneBot route flows, and QQ Markdown/button fallback behavior. The
comparison asserts full route-record equivalence on the seeded fixture. No
100k/1M database or full-suite pressure test was used.
