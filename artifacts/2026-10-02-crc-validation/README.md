# G2: Volcomp CRC32C validation on live shards — 2026-10-02

## Goal

Validate the `SHARD_INDEX_CHECKSUM_MISMATCH` finding (currently `low`
severity) against live data. The code comment says "low until a live run
shows mismatches are rare."

## Method

Ran `bin/scan_empty_chunks.py` over all 64 dl volcomp scroll volumes
(384 levels), with the current code that tracks `index_crc` per shard as
`verified` | `mismatch` | `unchecksummed` | `n/a`.

```bash
.venv/bin/python bin/scan_empty_chunks.py \
  --base https://dl.ash2txt.org/ \
  --levels-jsonl artifacts/2026-09-29-dl-regression/audit_pyramid.levels.jsonl \
  --only-sharded --random-roots 64 --seed 7 \
  --samples-per-level 4 --workers 6 \
  --out-dir artifacts/2026-10-02-crc-validation
```

## Results

| index_crc | count | % |
|---|---|---|
| verified | 1,167 | 58.1% |
| n/a | 510 | 25.4% |
| mismatch | 331 | 16.5% |

Total shards sampled: 2,008.

## Reading

**16.5% mismatch is not "rare."** However, severity stays at `low` for now
because the mismatches are not proven real:

1. The index parses successfully in all cases (structure is correct).
2. A 16.5% genuine corruption rate across the Vesuvius team's own writes
   is implausible.
3. More likely: our CRC calculation disagrees with the writer's on some
   shard layouts (e.g., edge shards, partial grids), or the checksum covers
   different bytes than we assume.

When a shard mismatches, we skip sampling it (offsets untrusted) — the
safe behavior. But raising 331 shards to `medium` without proving real
corruption would be crying wolf.

## Follow-up

- [ ] Manually verify 2–3 mismatching shards byte-by-byte against the Zarr v3
  spec to determine whether our `verify_index_checksum` or the writer is wrong.
- [ ] If our code is wrong: fix it, re-run, update this document.
- [ ] If the writer is wrong: raise severity with corpus evidence + CHANGELOG
  migration note per G2's definition of done.

## Artifacts

- `artifacts/2026-10-02-crc-validation/scan_empty_chunks.summary.json`
- `artifacts/2026-10-02-crc-validation/scan_empty_chunks.findings.csv`
- `artifacts/2026-10-02-crc-validation/scan_empty_chunks.manifest.json`
