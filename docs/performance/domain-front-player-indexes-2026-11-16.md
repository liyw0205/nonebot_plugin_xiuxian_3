# Domain-front player lookup performance

Date: 2026-11-16
Branch: `develop`
Database: temporary SQLite only; no repository `data/` database was used.

## Change

The domain-front participant, contribution, and claim tables now each have a
`player_id` index. The benchmark exercises the real OneBot and QQ dispatch
normalization paths for `我的状态`, `挂机状态`, `主线状态`, and `移动预览
玄天近郊`, then serializes the result through the OneBot text and QQ Markdown/
button helpers. The mainline evidence and location requirement EXPLAIN plans
were checked for player-index usage and absence of full scans.

## Same-dataset before/after

Command: `scripts/performance_benchmark.py --users 5000 --batch-size 500
--requests 40 --concurrency 1 10 50 --compare-domain-front-indexes`, with
`XIUXIAN_PERF_PROFILE=1`.

| Index state | Concurrency | p50 ms | p95 ms | p99 ms | CPU s | Peak RSS MiB | SQL | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Before | 1 | 1.944 | 3.942 | 67.251 | 0.188 | 111.086 | 170 | 0 |
| After | 1 | 1.983 | 2.983 | 6.002 | 0.092 | 125.168 | 170 | 0 |
| Before | 10 | 23.420 | 75.655 | 86.927 | 0.354 | 118.793 | 164 | 0 |
| After | 10 | 20.774 | 57.405 | 64.468 | 0.326 | 125.168 | 164 | 0 |
| Before | 50 | 72.426 | 100.934 | 101.704 | 0.183 | 119.051 | 170 | 0 |
| After | 50 | 62.046 | 94.856 | 97.323 | 0.183 | 125.168 | 170 | 0 |

Both runs reported `temporary_database_cleaned: true`. Query counts are equal
for each concurrency level; the indexed plan uses the three new player indexes,
the battle-session player index, and the existing archive/time-fort/livelihood
player indexes.

## Scale gates

All scale runs used `/home/nonebot-shared-venv/bin/python`,
`flock -w 600 /tmp/nonebot-project-validation.lock`, a temporary database,
`timeout 900s`, and `ulimit -v 4194304`. The scale run used 40 requests at
concurrency 1/10/50 and the database was removed by the benchmark context
manager after each run.

| Users | Seed DB bytes | Peak RSS MiB | Errors | Cleaned | Result |
| ---: | ---: | ---: | ---: | --- | --- |
| 100,000 | 385,588,704 | 163.641 | 0 | true | Passed the `<1 GiB` DB gate |
| 1,000,000 | 3,839,622,272 | 681.543 | 0 | true | Stopped: DB increment exceeded `<1 GiB` |

At the end of the 100,000 run, `/tmp` had about 9.12 GB available and
`MemAvailable` was about 1.29 GiB. At the end of the 1,000,000 run, `/tmp` had
about 7.40 GB available and `MemAvailable` was about 1.94 GiB. Both remained
above the required 5 GiB and 800 MiB runtime gates; the 1,000,000 run is not a
concurrency latency baseline because it was intentionally limited to one
request after the database-size gate failed.

## Verification

The focused suite ran under the shared lock and passed:

```text
3 passed in 5.96s
```

This covers the real status dispatch path for both adapters, the benchmark
contract, SQL query tracing, EXPLAIN assertions, zero errors, and temporary
database cleanup.
