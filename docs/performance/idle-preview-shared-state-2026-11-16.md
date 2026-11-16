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

One temporary 1,000-user SQLite fixture was reused by both variants. The
preview players had no active idle assignments and had 2,000 deterministic
daily-history rows (one `claimed` and one `expired` row per player across two
routes). Each variant ran 60 actual
`挂机预览` dispatches at concurrency 1/10/50, alternating OneBot and QQ
normalization, with SQL tracing and two counterbalanced repetitions per level:

```text
flock -w 600 /tmp/nonebot-project-validation.lock timeout 300s bash -c 'ulimit -v 4194304; /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py --users 1000 --batch-size 250 --requests 60 --concurrency 1 10 50 --command "挂机预览" --compare-idle-preview-state --profile-sql'
```

Each value is `p50 / p95 / p99 ms`; repeats are shown in execution order.

| Concurrency | Before: repeated route reads | After: shared request state |
| ---: | --- | --- |
| 1 | `18.716/28.083/29.214`; `18.584/19.710/28.995` | `12.880/13.571/14.971`; `12.925/13.751/16.082` |
| 10 | `632.212/708.256/728.051`; `633.968/699.309/706.644` | `246.063/303.402/305.470`; `244.569/304.745/320.218` |
| 50 | `1941.685/3828.004/3887.420`; `1953.235/3855.408/3908.576` | `740.292/1523.807/1579.826`; `746.787/1521.902/1563.262` |

All 720 measured requests returned without error, all preview records matched
field-for-field before and after, and both reports confirmed cleanup of the
temporary database. The seeded database was `29,331,904` bytes; the shared
post-run database was `16,969,728` bytes. Traced SQL fell from 35,940 per
60-request level to 2,340 (93.5% fewer statements). CPU seconds at c1/c10/c50
were `1.184/1.142`, `6.902/6.964`, `7.680/7.726` before and
`0.785/0.788`, `2.424/2.403`, `2.535/2.529` after. The process RSS
high-water was at most `132.19 MiB`; it is a process-wide high-water shared
across variants and is not presented as a per-variant memory reduction.

At c50 executor queue p95 fell from `3236.116/3269.220ms` to
`1270.112/1272.602ms`; eight workers were active in both variants. The active
idle lookup uses the existing covering player/status index. The grouped daily
count uses the existing player/status index and a small temporary B-tree for
`GROUP BY`; no index or schema change was added.

## Correctness and Limits

The focused shared-lock suite covers active idle/long-action messages, daily
route limits, location/reputation gates, malformed local-reputation JSON, the
real QQ/OneBot route flows, and QQ Markdown/button fallback behavior. The
comparison asserts full route-record equivalence on the seeded fixture. No
100k/1M database or full-suite pressure test was used.
