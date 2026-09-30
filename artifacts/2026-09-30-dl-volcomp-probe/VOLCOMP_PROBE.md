# Volcomp chunk-content probe — dl.ash2txt.org scroll volumes (2026-09-30)

## What this is

The scroll volumes the field actually trains on live on `dl.ash2txt.org`
as Zarr **v3** with the codec chain `sharding_indexed` (1024³ outer shards,
128³ inner chunks) → **volcomp** (lossy u8 CT codec, q=8.0). Until today
this repo could audit their *headers* but not read their *content*: the
volcomp codec had no Python decoder available to us.

We closed that gap: built `libvolcomp` from the upstream MIT-licensed
C library (superoptimizer/volume-compressor, commit `3e549a3`), vendored
the 166 KB Linux x86-64 decoder (`src/zpa/data/`, provenance recorded),
and taught `zpa-scan-chunks` to parse `sharding_indexed` shard indexes
over HTTP byte ranges and decode sampled 128³ inner chunks directly —
no zarr-python, no event loop, proxy-friendly.

## Run

```
zpa-scan-chunks --base https://dl.ash2txt.org/ \
  --levels-jsonl artifacts/2026-09-29-dl-regression/audit_pyramid.levels.jsonl \
  --only-sharded --random-roots 10 --seed 7 \
  --samples-per-level 4 --workers 6 \
  --out-dir artifacts/2026-09-30-dl-volcomp-probe
```

(`--random-roots` added nothing: with no `--root-filter` the run already
covered all 64 sharded roots.)

## Results

| metric | value |
|---|---|
| volcomp scroll volumes probed | 64 (all sharded roots on dl) |
| pyramid levels probed | 384 (6 per volume) |
| inner-chunk samples decoded | 548 populated, 2,118 missing |
| levels where every *present* chunk is empty | **0** |
| bytes fetched | 141 MB |

Sample statuses:

- `CHUNK_SAMPLE_POPULATED` [info] — decoded chunk holds non-fill voxels
  (e.g. center 16³ block 4096/4096 non-fill; 503,332 stored bytes →
  2,097,152 voxels). 548 samples.
- `CHUNK_SAMPLE_MISSING` [info] — inner chunk absent from the shard
  index, or the shard object itself absent. These read as fill_value
  legitimately: the volumes are *masked*, so background shards are
  simply not stored. 2,118 samples. Expected.
- `CHUNK_SAMPLE_EMPTY` (present chunk decodes to all fill) — **0
  samples**. The corruption class this probe hunts was not observed.

## Interpretation

Evidence of absence in the sample, not proof of absence corpus-wide:
every volcomp scroll volume on dl.ash2txt.org now has probed content at
all six pyramid levels, and no present-but-empty chunk was found. The
masked-out regions are genuinely unstored (missing), not zero-filled
impostors — the same silent-zero failure mode we proved on S3 does not
appear here.

## Method notes

- Per level: 4 shards spread across the shard grid × 3 inner chunks
  spread across each shard's inner grid (first/middle/last).
- Cheap first pass: decode only the central 16³ block of each chunk
  (`volcomp_decode_block`); full 128³ decode only when the block is
  empty, to confirm. Edge chunks are cropped to their valid region
  before the fill test.
- A level is flagged `CHUNK_SAMPLE_ALL_EMPTY` only if every *present*
  sampled chunk decodes to fill; missing chunks don't count toward the
  verdict.
