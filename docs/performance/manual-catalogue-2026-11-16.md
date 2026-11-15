# Manual catalogue status performance

Date: 2026-11-16
Branch: `develop`
Database: one temporary SQLite fixture reused for both variants; repository
runtime data was not modified.

## Change

`manual_rules` now caches only active item records whose `item_type` is
`manual`. The real `我的状态` dispatch path still validates owned manual
effects exactly as before; non-manual content remains outside that rule.

## Same-fixture before/after

Command:
`performance_benchmark.py --users 100 --batch-size 50 --requests 60
--concurrency 1 10 50 --command 我的状态 --profile-sql
--compare-manual-catalogue`.

| Variant | Catalogue records | Concurrency | p50 ms | p95 ms | p99 ms | CPU s | RSS high-water MiB | SQL | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Before: full item catalogue | 1970 | 1 | 2.094 | 2.589 | 56.739 | 0.189 | 105.871 | 361 | 0 |
| After: manual-only catalogue | 19 | 1 | 1.699 | 1.987 | 51.888 | 0.159 | 115.895 | 360 | 0 |
| Before: full item catalogue | 1970 | 10 | 28.257 | 78.131 | 85.035 | 0.400 | 112.035 | 360 | 0 |
| After: manual-only catalogue | 19 | 10 | 23.604 | 32.961 | 34.973 | 0.272 | 115.895 | 360 | 0 |
| Before: full item catalogue | 1970 | 50 | 84.966 | 183.779 | 188.060 | 0.305 | 112.289 | 360 | 0 |
| After: manual-only catalogue | 19 | 50 | 77.184 | 170.089 | 176.125 | 0.291 | 115.895 | 360 | 0 |

Seed metadata was identical (`users=100`, seed DB `7,691,912` bytes); the
post-run database size was `4,173,824` bytes for both variants and both
temporary directories reported `temporary_database_cleaned: true`. The
benchmark exercised the actual adapter normalization, application dispatch,
and response serialization path, with SQL profiling enabled and no command
errors. The RSS field is the process `ru_maxrss` high-water value; because both
variants intentionally share one process, it is not an independent per-run
peak and is reported only as a resource bound, not as an optimization claim.

## Validation flow

Correctness and performance are separate layers under
`/tmp/nonebot-project-validation.lock`. Correctness is one pytest invocation
covering the existing player/status/stat behavior plus breakthrough/manual
rules; the run passed `129 passed, 1 deselected in 27.657s`. Performance is one
bounded same-fixture before/after invocation. No full-scale or million-user
run was used for this change.
