# Mainline status prerequisite preparation

Date: 2026-11-16

Branch: `develop`

Baseline: `23dd5ac`

Environment: `/home/nonebot-shared-venv/bin/python`; Linux runtime/install
defaults remain `/root/myenv`.

## Change

The mainline status path previously rebuilt completed-stage and event sets,
looked up the same stage definitions, and normalized completed stage keys for
each of 41 stage definitions. Status now prepares these shared values once and
evaluates the full stage list in one pass. The existing single-stage public
prerequisite API remains unchanged. Effective run snapshots are still resolved
before evaluation, so a running stage keeps the rules frozen when it started.

## Same-fixture comparison

Command:

```text
flock -w 600 /tmp/nonebot-project-validation.lock timeout 300s bash -c 'ulimit -v 4194304; XIUXIAN_PERF_PROFILE=1 /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py --users 1000 --batch-size 250 --requests 60 --concurrency 1 10 50 --command "主线状态" --profile-sql --compare-mainline-prerequisites'
```

Both variants used the same 1,000-user seed (`7,691,912` bytes), runtime,
SQLite file, OneBot/QQ normalization and response serialization. Each variant
was measured twice per concurrency level with order alternated; the table shows
the second, counterbalanced round. Both rounds had zero errors. At each level
the second round collected exactly 180 SQL statements per variant and kept the
same indexed player, mainline-progress, and evidence plans. The temporary DB
was removed (`temporary_database_cleaned: true`); post-run DB size was
`5,877,760` bytes for both variants.

| Concurrency | Variant | Response p50/p95/p99 ms | Repository p50/p95/p99 ms | CPU s | Process RSS high-water MiB |
| ---: | --- | --- | --- | ---: | ---: |
| 1 | Per-stage | 2.755 / 2.941 / 3.627 | 2.155 / 2.302 / 3.007 | 0.173 | 104.680 |
| 1 | Shared preparation | 1.264 / 1.394 / 1.434 | 0.669 / 0.751 / 0.847 | 0.083 | 104.680 |
| 10 | Per-stage | 23.495 / 36.699 / 37.211 | 21.060 / 32.126 / 35.536 | 0.271 | 112.387 |
| 10 | Shared preparation | 15.022 / 20.608 / 22.138 | 12.541 / 16.877 / 18.499 | 0.177 | 112.387 |
| 50 | Per-stage | 80.038 / 172.914 / 180.877 | 24.014 / 39.972 / 47.207 | 0.274 | 112.641 |
| 50 | Shared preparation | 43.932 / 99.656 / 102.914 | 14.115 / 24.622 / 25.464 | 0.182 | 112.641 |

The first round exposed cold executor connection noise: c10 shared-preparation
p95/p99 were `89.137/94.792ms` while new worker connections opened, and c1's
first per-stage round had a single `35.681ms` tail sample. The counterbalanced
round retained the response and repository improvements at all levels. RSS is
the process-wide `ru_maxrss` high-water value, not an independent per-variant
peak; it did not increase between variants.

## Verification

Under the shared lock, with a 4 GiB virtual-memory limit:

```text
6 passed in 6.93s
```

This covered batch-vs-single prerequisite equivalence across all bundled mainline
definitions and multiple progress/realm states, snapshot behavior after current
content changes, invalid snapshot diagnostics, existing start-gate behavior,
SQL-profile reporting, and the same-fixture comparator cleanup contract.
