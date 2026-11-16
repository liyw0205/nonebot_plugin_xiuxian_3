# Arena season top-N response performance

Date: 2026-11-16

Branch: `develop`

Baseline: `f4e23f2`

Runtime boundary: Linux install/runtime remains `/root/myenv`; the shared
interpreter is used only for local development, tests, and this benchmark.

## Measured hotspot and change

The actual read-only `竞技场赛季` path fetched 1,000 immutable matches, built
the current and previous boards, sorted every player, and then returned only
the configured top 20. The history query already used
`idx_arena_matches_settled_events` as a covering index. `build_board()` now
accepts an optional limit and uses `heapq.nsmallest` with the same total ranking
key when a consumer only needs the first N entries. Its default remains a full
ranking for callers that need every entry.

## Same-fixture comparison

One deterministic temporary SQLite database contained 1,000 users and 1,000
arena matches (29,331,904 bytes before runtime close). The same database was
used for both variants, with 60 actual `竞技场赛季` dispatches at concurrency
1/10/50 and two counterbalanced repeats per level. Requests used the OneBot and
QQ normalization paths; no live QQ account was used. Both reports had zero
errors, the direct repository payloads were equal, the query plan stayed on the
covering index, and the owned temporary database was removed after the run.

Command:

```text
timeout 360s flock -w 600 /tmp/nonebot-project-validation.lock /bin/bash -lc 'ulimit -v 4194304; /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py --users 1000 --batch-size 250 --requests 60 --concurrency 1 10 50 --command "竞技场赛季" --profile-sql --compare-arena-season-top-n'
```

Each cell is `p50 / p95 / p99 ms`; repeated results are kept separate.

| Concurrency | Full sort then slice, repeat 1; repeat 2 | Top-N, repeat 1; repeat 2 |
| ---: | --- | --- |
| 1 | 13.658 / 15.651 / 66.668; 13.679 / 16.173 / 57.025 | 10.934 / 12.950 / 53.722; 10.838 / 11.296 / 11.754 |
| 10 | 451.245 / 552.942 / 569.552; 502.067 / 584.121 / 616.555 | 436.907 / 537.133 / 573.133; 455.227 / 535.100 / 548.308 |
| 50 | 1497.338 / 2866.779 / 2910.399; 1473.282 / 2949.064 / 2989.375 | 1310.634 / 2738.024 / 2782.693; 1384.675 / 2931.365 / 2967.625 |

Both repeats improved p95 at every concurrency. The single-repeat c10 p99
change of `569.552 -> 573.133ms` is within run variation; the second repeat
improved from `616.555 -> 548.308ms`. At c50, p95 improved by 4.5% and 0.6%,
and p99 by 4.4% and 0.7%; the clearest benefit is on the single-request path,
where p95 fell by 17.2% and 30.2% across repeats.

CPU seconds by repeat were c1 `0.896/0.923 -> 0.754/0.660`, c10
`5.147/5.735 -> 5.095/5.168`, and c50 `5.762/5.962 -> 5.755/6.178`. Process
RSS high-water was 118.125 MiB at c1 and at most 127.121 MiB at c10/c50; this
is a process-wide high-water, not a per-variant peak. Connection counts were
2-3 at c1 and 9 at c10/c50. SQL counts remained 360 per 60-request level,
except one cold c1 round that traced 361. No SQL work was removed by this
change.

The 8-worker executor queue remains the main c50 tail source: queue-wait p95
was `2564/2650ms` before and `2311/2544ms` after, while connection-open p95
was below `0.01ms`. This optimization reduces ranking work but does not claim
to solve executor saturation.

## Verification and limits

The concentrated shared-lock correctness run completed with `170 passed, 2
deselected` in 68.82 seconds. It included arena settlement, ranking, response,
and the other benchmark-contract coverage. The tiny top-N comparator test is
excluded from this layer because the performance layer runs that exact
comparison once on its 1,000-user fixture and checks ranking equivalence,
zero errors, SQL collection, and cleanup. The test remains available in the
regular suite. The benchmark used the 1,000-user fixture only; no 100k/1M
fixture was run. CI for the resulting push remains pending.
