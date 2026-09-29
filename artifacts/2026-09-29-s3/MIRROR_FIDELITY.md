# Mirror fidelity: S3 vs dl.ash2txt.org — 2026-09-29

64 volumes exist under the same file name in both the open-data S3 bucket
and dl.ash2txt.org. Same name does **not** mean same bytes.

## Method

Stem-matched the 64 pairs across the two audits
(`artifacts/2026-09-29-s3/` vs `artifacts/2026-09-09/`), then compared
per-level shape, chunk grid, dtype and codec, plus the finding sets.

## Result

All 64 pairs are **format migrations, not copies**:

| | dl.ash2txt.org copy | S3 copy |
|---|---|---|
| Zarr format | v3 | v2 |
| chunking | 1024³, `sharding_indexed` | 128³, plain |
| codec | volcomp (lossy, q=1.0) | none (raw uint8) |
| dtype | uint8 | \|u1 (same type) |

- Voxel grids are identical at all 6 levels for **64/64** pairs.
- S3 chunks verified on the wire: exactly 2,097,152 bytes (128³ uint8),
  sparsely stored (only non-fill chunks), holding plausible CT data
  (background 0, tissue ~38–42).
- 39 of the 64 dl copies carry info-level `CHUNK_EXCEEDS_SHAPE` (1024³
  chunks overhang the small level-5 shapes); 0 of the 64 S3 copies do —
  the 128³ rechunking eliminates it. Every S3 mirror is audit-clean.
- The S3 bucket's 70 native v3 roots are a disjoint set (zero stem
  overlap with dl's 64 v3 roots): the bucket hosts both new v3 publishes
  and v2 rechunks of older dl volumes.

## Why it matters

Anyone joining analyses across the two stores by file name — or assuming a
checksum from one store validates the other — is comparing different
encodings of the same voxel grid. Reproducibility work must pin the
store, not just the name.

## Byte-level check (done 2026-09-29)

Built the volcomp decoder (`superoptimizer/volume-compressor`, C library +
Python ctypes binding) and compared two 128³ chunks of
`20260309142202-2.399um-0.2m-78keV-masked.zarr` level 5 — S3 raw v2 chunk
vs volcomp-decoded dl inner chunk over the same voxel region:

| chunk | max abs diff | mean abs diff | voxels differing |
|---|---|---|---|
| (0,3,1) | 35 | 0.091 | 3.72% |
| (0,4,4) | 30 | 0.044 | 1.71% |

Not bit-identical — and not expected to be: the dl copy is the
lossy volcomp (q=1.0) derivative, the S3 copy the raw variant. The
differences have the classic quantization-noise signature (mostly ±1–8,
decaying histogram, no mask-boundary artifacts). The S3 migration
preserves the raw values; the dl copy is its lossy compression. Same
voxel grid, scientifically equivalent, different encodings.

Bottom line for reproducibility: pin the store, not just the file name.
A checksum from one store does not validate the other.
