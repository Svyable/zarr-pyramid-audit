# dl.ash2txt.org v2 content probe (2026-09-30)

## What this is

Content-level companion to the header-only audit. Every present v2
(raw / Blosc) pyramid level on `dl.ash2txt.org` gets K=3 chunks sampled
across its chunk grid (first/middle/last spread, 9 candidates); each
chunk is fetched and decoded, then classified:

- `populated` — decodes with non-fill voxels
- `empty` — present chunk decodes to all fill_value (review flag)
- `absent` — chunk key not stored (sparse levels; informational)
- `undecodable` — codec the probe can't read (never misread as raw)
- `CHUNK_SAMPLE_ALL_EMPTY` [medium] — every *present* sampled chunk of
  a level decodes to fill: the corruption class this probe hunts
- `CHUNK_LEVEL_NO_CHUNKS` [info] — level holds no stored chunks at all
  (audit-flagged `has_chunks=false`, probe-confirmed)
- `CHUNK_LEVEL_NO_SAMPLES` [info] — sparse level the spread sampling
  could not cover; a coverage gap, not a finding

## Run

```
zpa-scan-chunks --base https://dl.ash2txt.org/ \
  --levels-jsonl <748 v2 levels from the 2026-09-29 dl regression> \
  --samples-per-level 3 --workers 8 \
  --out-dir artifacts/2026-09-30-dl-v2-probe
```

## Results

| metric | value |
|---|---|
| v2 roots probed | 128 |
| v2 levels probed | 748 of 748 (no silent drops) |
| chunk samples decoded | 1,795 populated, 17 empty |
| levels where every present chunk is empty | 7 |
| audit-flagged chunkless levels, probe-confirmed | 11 |
| sparse levels spread sampling couldn't cover | 59 (reported, not dropped) |
| undecodable / fetch errors | 0 |
| bytes fetched | 1.46 GB |

### The finding: a present-but-empty pyramid

`other/dev/meshes/20231022170900-ome.zarr` — levels **1–7 decode to
all zeros** while level 0 holds real mesh content (543K/364K nonzero
voxels in sampled L0 chunks). Verified beyond sampling:

- 12/12 spread chunks of L1 decode to all fill_value
- L1 chunk (0,0,3) — the exact 2×-downscaled counterpart of populated
  L0 chunk (1,1,6) — is all zeros (a real downscale cannot annihilate
  543K nonzero voxels)
- 10/10 HEAD-sampled L1 chunk keys are byte-identical 8,528-byte
  blosc(lz4) zero-blobs: the levels are uniformly zero-filled, not
  sparsely empty
- The root exists only on dl (not in the S3 bucket)

Caveats, stated plainly: this is `other/dev/`, a dev-directory mesh
derivative — not a scroll volume. It may be a placeholder pyramid
someone wrote deliberately rather than bit-rot. Either way, 7 of 8
levels contain no data, which is exactly the silent-corruption class
header-only audits cannot see — and this probe caught it on its first
full-corpus run.

### Coverage notes

- The 11 audit-flagged chunkless levels (`has_chunks=false`, incl. the
  known `3336_predictions.zarr` and `1-voxel-sheet_slices-closed.zarr`
  defectives) are confirmed chunkless at probe time
  (`CHUNK_LEVEL_NO_CHUNKS`).
- 59 sparse mask/surface/label levels the spread sampling couldn't cover
  are reported as `CHUNK_LEVEL_NO_SAMPLES` — a coverage gap, never
  silently dropped. Binary masks occupy a tiny fraction of chunks, so 9
  spread candidates can legitimately miss; denser targeted sampling is
  future work.

## Interpretation

Together with the volcomp probe (all 64 scroll volumes, 384 levels),
every content-decodable pyramid level on dl.ash2txt.org now has sampled
content evidence. The present-but-empty class is no longer theoretical:
one live pyramid exhibits it.
