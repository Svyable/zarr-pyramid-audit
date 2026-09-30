# Chunk-content probe, v3 sharded levels — 2026-09-30

Extension: `lib/chunkscan.py::probe_level_v3_sharded` + `--only-sharded` flag.
The 70 Zarr v3 roots on S3 (420 levels, `sharding_indexed`) are not directly
addressable by chunk key, so they are probed through zarr-python window reads
(3 spread windows per level via s3fs) instead of individual chunk downloads.

## Run (2026-09-30, s3://vesuvius-challenge-open-data)

- 70 roots, 420 levels, 1,260 windows sampled.

## Result

- **1,224/1,260 windows populated** (contain non-fill data).
- 36 windows empty — scattered single windows (never all 3 in any level),
  consistent with background regions of ink-detection max-projection volumes.
- **0 levels** where every sampled window was empty.

## Combined with the v2 run

- v2 raw/blosc: 58 roots / 291 levels / 788 chunks — 788/788 populated.
- v3 sharded: 70 roots / 420 levels / 1,260 windows — 1,224 populated,
  36 background-empty, 0 all-empty levels.
- Every decodable level class in the S3 bucket is now covered by a
  content probe. The present-but-empty defect class remains unobserved.
