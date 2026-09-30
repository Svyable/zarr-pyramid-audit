# Chunk-content probe — 2026-09-30

New tool: `bin/scan_empty_chunks.py` (+ `lib/chunkscan.py`). The header-only
audit answers "are chunk keys present?"; this answers the next question —
"do the chunks that are present actually hold data?" A chunk that exists but
decodes to all fill_value is the next silent-corruption class: zarr opens it,
reads return plausible voxels, nothing raises.

Method: K=3 sampled chunks per level (first/middle/last of the chunk grid),
up to 9 candidates to tolerate sparse levels. v2 raw and v2 blosc decoded;
v3 shards reported as undecodable, never silently skipped. Two-phase fetch
for uncompressed chunks (nonzero byte in the first 4 KiB proves population).

## Run (2026-09-30, s3://vesuvius-challenge-open-data)

- 58 roots: all 19 copies of the defective stem
  (`1.129um-0.22m-59keV-volume-20260521123630-L1.zarr`; the defective copy
  has no chunks and is auto-skipped) + 40 seeded random roots.
- 291 levels scanned, 788 chunks sampled and decoded, 213 MB fetched.

## Result

- **788/788 sampled chunks populated** (contain non-fill data).
- **0 levels** where every sampled chunk was empty.
- The 18 clean siblings of the defective volume are genuinely populated
  with real voxel data at all 6 levels — not present-but-empty.

## Interpretation

The present-but-empty defect class was not observed in this sample. The
missing-chunks (header-only) class remains the only silent-corruption mode
seen in the bucket. An all-empty sample would have been a medium-severity
review flag (genuinely empty background regions exist), so this negative
result is reported as what it is: evidence of absence in the sample, not
proof of absence in the corpus. The tool is published for anyone to rerun
at larger K.
