# Cooperative DP pool correctness audit (2026-08-13)

## Result

The former coordinator could miss valid cross-worker collisions. RCKangaroo
streams the 22 raw bytes of `EcInt`; this is a signed, little-endian value.
The Python server parsed the printed bytes as unsigned big-endian and tried
heuristic `difference`, `difference/2`, and offset candidates.

The coordinator now mirrors `Collision_SOTA`: signed distance decoding;
tame/wild and same-wild branches; both signs; reversal of RC main-mode's
`start` and `2^(range_bits-5)` transformation; and final secp256k1 verification.
The matcher fetches and deduplicates whole batches instead of issuing two SQL
queries per DP. Sessions now return the actual job `start_hex`.

## Positive controls

From `pool/server` run:

```powershell
python -m unittest -v test_collision_sota.py test_pool_integration.py
```

Six controls pass. The integration control creates two independent worker
sessions, submits planted tame and wild DPs through the SQLite endpoint, and
verifies the exact recovered private key.

## Capacity boundary

The optimized local path measured about 38,800 records/s for 100,000 synthetic
unique records in 500-record batches. This is not a VPS/network guarantee.

`aggregate_DP_rate ~= aggregate_key_rate / 2^dp_bits`

For 100 RTX 5090 at 15 Gkey/s each:

| DP bits | Approximate pool input |
|---:|---:|
| 20 | 1,430,511 DP/s |
| 28 | 5,588 DP/s |
| 30 | 1,397 DP/s |
| 31 | 698 DP/s |
| 32 | 349 DP/s |

Use `dp30`-`dp31` only after RC reports acceptable DP overhead.

## Remaining gate

1. Deploy to an isolated test database.
2. Solve known P70/P80 using DPs from at least two processes.
3. Repeat with 1/2/4/8 GPUs and measure queue, ingestion, DB growth and result.
4. Do not launch a large cluster until every run recovers the exact known key.

This pool reduces zero bits and does not change the square-root work factor.
