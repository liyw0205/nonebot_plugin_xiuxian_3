# Player profile projection reuse

Date: 2026-11-16
Branch: `develop`
Runtime boundary: Linux installation/runtime remains `/root/myenv`; the
shared interpreter was used only for this bounded local benchmark.

## Hotspot and change

The real `我的状态` path built a player stat snapshot and then normalized the
same SQLite player row again while constructing `PlayerView`. The stat builder
also normalized its prepared JSON input independently. The change strictly
decodes the qualification and inventory objects once, passes the detached
normalized projection into the stat calculation, and reuses it for
`PlayerView`. SQL, connection creation, transaction boundaries, unknown fields,
and OneBot/QQ response contracts are unchanged.

The query profile showed indexed player/equipment/constitution/companion reads;
connection-open time was below 0.01 ms and no full-table scan was introduced.

## Same-fixture comparison

One deterministic 100-user temporary SQLite fixture was used for both variants.
Each variant ran four counterbalanced repetitions at concurrency 1, 10, and 50,
with 60 real `我的状态` requests per level. An equal discarded warmup batch
preceded every measured variant to remove executor thread-creation order from
the steady-state comparison. Requests used both OneBot text and QQ Markdown/
button normalization and response serialization.

```text
flock -w 600 /tmp/nonebot-project-validation.lock bash -lc \
  'ulimit -v 4194304; timeout 900s \
  /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py \
  --users 100 --batch-size 50 --requests 60 --concurrency 1 10 50 \
  --command "我的状态" --profile-sql --compare-player-profile-projection'
```

Values below are medians of the four repetitions (`p50/p95/p99`, milliseconds).

| Concurrency | Before duplicate projection | After shared projection | CPU s before/after | RSS MiB | Connections | SQL / level | Errors |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.440 / 1.549 / 1.712 | 1.342 / 1.446 / 1.554 | 0.092 / 0.087 | 109.758 | 2 | 360 / 360 | 0 |
| 10 | 20.221 / 27.581 / 28.825 | 19.538 / 26.088 / 26.884 | 0.228 / 0.222 | 116.434 | 8 | 360 / 360 | 0 |
| 50 | 63.511 / 137.575 / 140.805 | 61.684 / 130.507 / 133.531 | 0.242 / 0.234 | 116.949 | 8 | 360 / 360 | 0 |

The normalization counter was `120 -> 60` per measured level. Every response
projection was equivalent, the benchmark reported zero command errors, and the
temporary database directory was removed. The seed database was 7,663,144
bytes; both variants used the same seed and post-close database size
5,169,152 bytes. A single c1 p99 maximum showed normal executor jitter; the
repeated medians improved at every level and c10/c50 p95 and p99 improved in
all four repetitions.

## Verification

The focused correctness run passed under the shared lock with the shared
development interpreter and a 4 GiB virtual-memory limit:

```text
94 passed
```

The focused performance comparator passed with equivalent OneBot/QQ outputs,
strict JSON validation, SQL tracing, and cleanup assertions. No 100k/1M
fixture was created.
