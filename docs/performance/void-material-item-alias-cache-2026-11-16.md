# Void-material item alias cache

Date: 2026-11-16  
Branch: `develop`  
Runtime boundary: Linux installation/runtime remains `/root/myenv`; the
shared interpreter was used only for the bounded local benchmark.

## Hotspot and change

The real `寄售物资 虚空晶体 1 100` command resolves an item before entering its
transaction. The old path deep-copied and linearly scanned all active item
records on every request (1,970 records in this fixture), even though the
content bundle is immutable for the lifetime of the application. The
application now builds a key/name/alias map once per `ContentBundle` identity;
replacing the bundle rebuilds it. Alias order, active-item filtering, and the
admission gate are unchanged.

The fixture's player is intentionally below the void-market admission gate, so
the expected public response is `VOID_MARKET_ADMISSION`. The benchmark contract
was corrected from the stale `VOID_MARKET_NOT_ENOUGH_ITEMS` expectation; no
business gate was changed.

## Same-fixture before/after

Command (one seed, two counterbalanced repetitions per concurrency):

```text
flock -w 600 /tmp/nonebot-project-validation.lock timeout 600s bash -lc 'ulimit -v 4194304; /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py --users 100 --batch-size 50 --requests 60 --concurrency 1 10 50 --command "寄售物资 虚空晶体 1 100" --profile-sql --compare-void-material-item-cache'
```

The seed database was `7,663,144` bytes with `1,970` active item records. Both
variants used the real OneBot/QQ normalization, application dispatch, and
response serialization. Responses were equivalent, errors were zero, SQL was
unchanged at 300 statements per level, and the temporary database directory was
removed.

| Concurrency | Variant | p50 ms (repeats) | p95 ms (repeats) | p99 ms (repeats) | CPU s | RSS MiB | Alias builds |
| ---: | --- | --- | --- | --- | --- | ---: | ---: |
| 1 | Before | 42.240 / 41.236 | 82.176 / 81.487 | 92.207 / 85.590 | 2.882 / 2.808 | 111.473 | 60 / 60 |
| 1 | After | 0.867 / 0.866 | 1.028 / 0.947 | 42.006 / 80.895 | 0.100 / 0.138 | 111.473 | 1 / 1 |
| 10 | Before | 277.893 / 261.100 | 484.706 / 485.904 | 506.878 / 512.404 | 2.961 / 2.984 | 117.637 | 60 / 60 |
| 10 | After | 10.461 / 10.341 | 47.756 / 21.227 | 57.917 / 51.667 | 0.258 / 0.149 | 117.637 | 1 / 1 |
| 50 | Before | 1,012.872 / 1,065.091 | 2,424.794 / 2,351.963 | 2,557.243 / 2,475.815 | 3.063 / 2.995 | 118.129 | 60 / 60 |
| 50 | After | 26.432 / 24.082 | 51.245 / 53.954 | 74.981 / 123.860 | 0.135 / 0.183 | 118.129 | 1 / 1 |

The after p99 values are still subject to executor scheduling noise, but each
concurrency level is materially below its before counterpart; no tail
regression, response change, SQL change, RSS increase, or connection increase
was observed.

## Verification

The focused shared-lock suite passed: `9 passed`. It covers the real gate
response, OneBot/QQ comparator, content replacement invalidation, existing void
material behavior, zero errors, and temporary fixture cleanup. No 1k/100k/1M
fixture was created for this phase.
