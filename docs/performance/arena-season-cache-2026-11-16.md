# Arena season board cache

Date: 2026-11-16  
Branch: `develop`  
Runtime boundary: Linux installation/runtime remains `/root/myenv`; the
shared interpreter was used only for the bounded local benchmark.

## Hotspot and change

The real `竞技场赛季` command rebuilt the same immutable `arena_matches`
history into `MatchEvent` objects and ran `build_board` for every request. At
1,000 seeded users the traced SQL was already indexed, but the application
stage dominated: c1 was about 10 ms and c10/c50 were about 425/488 ms. The
repository now keeps event and board results per thread-local SQLite connection
and content identity. `PRAGMA data_version` detects commits from other
connections, and arena match insertion increments a generation to invalidate
the cache for local writes. Frozen settlement rows, rewards, ordering, and
content replacement remain unchanged.

## Same-fixture before/after

Command (one seed, two counterbalanced repetitions per concurrency):

```text
flock -w 600 /tmp/nonebot-project-validation.lock timeout 600s bash -lc 'ulimit -v 4194304; /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py --users 1000 --batch-size 250 --requests 20 --concurrency 1 10 50 --command "竞技场赛季" --profile-sql --compare-arena-season-cache'
```

The seed database was `29,331,904` bytes (`1,000` users and matches). Both
variants used the real OneBot/QQ normalization, application dispatch, and
response serialization. The output payloads were equivalent, errors were zero,
and the temporary database directory was removed.

| Concurrency | Variant | p50 ms (repeats) | p95 ms (repeats) | p99 ms (repeats) | CPU s | RSS MiB | SQL | Connections |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: |
| 1 | Before | 11.313 / 11.150 | 20.661 / 11.551 | 61.767 / 11.826 | 0.295 / 0.226 | 119.5 | 121 / 120 | 2 |
| 1 | After | 1.255 / 1.262 | 11.067 / 11.027 | 11.425 / 11.218 | 0.047 / 0.047 | 119.5 | 102 / 102 | 2 |
| 10 | Before | 492.298 / 334.790 | 563.938 / 493.257 | 579.895 / 497.299 | 1.938 / 1.379 | 128.5 | 120 / 120 | 8 |
| 10 | After | 29.634 / 33.481 | 346.318 / 355.074 | 352.155 / 372.254 | 0.721 / 0.641 | 128.5 | 108 / 108 | 8 |
| 50 | Before | 640.259 / 935.414 | 1,079.080 / 1,176.742 | 1,088.814 / 1,186.480 | 1.838 / 2.045 | 128.5 | 120 / 120 | 8 |
| 50 | After | 500.959 / 281.805 | 555.743 / 504.203 | 565.637 / 504.910 | 1.004 / 0.867 | 128.5 | 108 / 108 | 8 |

The c10/c50 tail includes executor queue scheduling, but both measured p95 and
p99 values improved in both counterbalanced repetitions. The per-stage
`arena_season_board` p50 fell to `0.9-27.1 ms` after caching; no connection or
RSS increase was observed.

## Verification

The focused suite passed under the shared lock with a 4 GiB virtual-memory
limit: `13 passed`. It covers arena settlement behavior, output equivalence,
SQL/profile reporting, cache invalidation after a newly settled match, and
temporary fixture cleanup. No 100k/1M fixture was created.
