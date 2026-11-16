# Equipment preview bundle cache

Date: 2026-11-16
Branch: `develop`
Scope: real OneBot text and QQ normalization/application dispatch for `法器预览`
and `重铸预览`; temporary SQLite only.

## Change

`EquipmentApplication` now caches validated equipment definitions by immutable
`ContentBundle` identity. Replacing the content bundle rebuilds the definitions;
a failed rebuild leaves the last valid cache untouched. Player state, costs,
labels, malformed-content diagnostics, and response contracts are unchanged.

## Same-fixture evidence

The comparator used one deterministic 100-user fixture, two counterbalanced
rounds, both adapters, and 20 requests at each measured concurrency. The seed
database was 7,663,144 bytes with 1,970 active item records and 1,866 equipment
definitions. Responses were byte-equivalent at the `CommandResult` contract,
SQL errors were zero, and the temporary database was removed after the run.

| Metric | Before: rebuild each request | After: bundle-identity cache |
| --- | ---: | ---: |
| Definition builds per 20-request round | 20 | 1 |
| p50 range across measured levels | 918-947 ms | 223-246 ms |
| p95 range across measured levels | 993-1,012 ms | 301-316 ms |
| p99 range across measured levels | 955-999 ms | no regression observed |
| CPU high-water range | 18.7-18.9 s | 5.9-6.1 s |
| RSS high-water bound | about 139 MiB | about 139 MiB |
| Errors | 0 | 0 |

The benchmark measured end-to-end dispatch and response serialization, not only
the parser. No SQL query was attributed to the preview commands themselves;
their cost was content validation/build work. The cache comparator also asserts
rebuild on bundle replacement and preservation of the last valid cache after a
malformed rebuild.

## Validation

Equipment/content targeted tests and the shared performance regression contract
passed before commit `66e4228`; develop CI `43844306597` passed install-smoke
and quality on Python 3.11/3.12. Linux runtime/install defaults remain
`/root/myenv`; the shared interpreter is development-only.
