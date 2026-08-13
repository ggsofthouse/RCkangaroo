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

### Real RCKangaroo P70 control

Run:

```powershell
python pool/controls/real_p70_cross_process_control.py
```

Validated on the local RTX 2060 Super with two separate RC processes at dp18:

- process 1 generated and submitted 296,978 real tame DPs in 76.940 s;
- process 2 submitted 87,080 real wild DPs in 35.269 s;
- the coordinator found the cross-process collision;
- the recovered scalar exactly matched solved Puzzle 70;
- total wall time was approximately 112.2 s.

This validates the complete RC stdout -> parser -> SQLite -> Collision_SOTA ->
secp256k1 verification path. P80 is not required to establish another protocol
property; it remains a longer performance/regression control.

The run also exposed that RC constructs a streamed DP line with multiple
`printf` calls. An overflow message can interleave with its hexadecimal field.
The worker now accepts only an exact `type:24-hex:44-hex` record, so malformed
interleaved output is rejected rather than submitted.

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
2. P70 cross-process recovery: **passed**.
3. Optionally run P80 as a longer regression/performance control.
4. Repeat with 1/2/4/8 GPUs and measure queue, ingestion, DB growth and result.
5. Do not launch a large cluster until every scaling run recovers an exact known key.

This pool reduces zero bits and does not change the square-root work factor.
