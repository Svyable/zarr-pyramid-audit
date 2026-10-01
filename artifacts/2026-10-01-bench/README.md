# Audit cost benchmark — 2026-10-01

What one audit costs on public S3 pyramids: latency, store calls and payload
bytes for the header-only audit, then for the sampled chunk-content probe
(3 samples per level). Six roots from `s3://vesuvius-challenge-open-data`:
the defective PHerc0814 surface volume, its populated sibling, a raw v2
surface volume, a Blosc/zstd surface prediction, a raw v2 masked scroll volume,
and a v3 sharded ink-detection volume.

```bash
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
P=PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes
zpa-bench --base s3://vesuvius-challenge-open-data/ \
  --root "$P/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr" \
  --root "$P/2.399um-0.22m-78keV-volume-20260309142202.zarr" \
  --root "PHerc1447/segments/20250702235910-auto_grown_20250702235910292/surface-volumes/8.64um-1.2m-116keV-volume-20250521151220.zarr" \
  --root "PHerc0009B/representations/predictions/surfaces/20260319104112-surface-20260413222639-surface-m7-L2-th0.2.zarr" \
  --root "PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr" \
  --root "PHercParis4/segments/20260603024952-5753_-2/ink-detection/PHercParis4-20260603024952-2.4um-0.22m-78keV-volume-20260411134726-L2-3d-ink-max.zarr" \
  --samples-per-level 3 --out-dir artifacts/2026-10-01-bench
```

Files: `bench.jsonl` (one record per root, all counters), `bench.summary.md`
(the table below), `bench.manifest.json` (argv, host, package versions).
`bench.summary.md` was re-rendered from `bench.jsonl` after a cosmetic fix to
the table formatter (an empty status list printed a leading `; `); no number
changed.

## Results

| root | levels | header audit: time · requests (meta/list/head) · payload | findings | chunk probe: time · reads · payload | probe result |
|---|---|---|---|---|---|
| `1.129um-0.22m-59keV-volume-20260521123630-L1.zarr` | 6 | 1.77 s · 16 (8/6/2) · 4.6 KiB | LEVEL_NO_CHUNKS (FAIL) | 4.35 s · 0 reads + 41 HEAD · 0 B | CHUNK_LEVEL_NO_CHUNKS |
| `2.399um-0.22m-78keV-volume-20260309142202.zarr` | 6 | 1.50 s · 16 (8/6/2) · 4.6 KiB | none (PASS) | 5.39 s · 20 reads + 19 HEAD · 5.0 MiB | populated 17 |
| `8.64um-1.2m-116keV-volume-20250521151220.zarr` | 6 | 1.75 s · 16 (8/6/2) · 3.6 KiB | none (PASS) | 1.23 s · 13 reads + 25 HEAD · 877.7 KiB | populated 13; CHUNK_LEVEL_NO_SAMPLES |
| `20260319104112-surface-20260413222639-surface-m7-L2-th0.2.zarr` | 6 | 1.52 s · 16 (8/6/2) · 5.3 KiB | none (PASS) | 6.64 s · 12 reads + 46 HEAD · 2.8 MiB | populated 12 |
| `20250521140437-8.640um-1.2m-116keV-masked.zarr` | 6 | 1.47 s · 16 (8/6/2) · 4.4 KiB | none (PASS) | 6.89 s · 21 reads + 33 HEAD · 8.1 MiB | populated 17 |
| `PHercParis4-…-L2-3d-ink-max.zarr` (v3 sharded) | 6 | 2.30 s · 22 (14/6/2) · 8.9 KiB | none (PASS) | not measured (sharded v3) | — |

## How to read it

- **Header audit ≈ 1.5–2.3 s, 16–22 store calls, < 9 KiB per pyramid**,
  independent of array size (the masked scroll volume's level 0 is
  17998 × 8595 × 8595 voxels per `../2026-09-29-s3/audit_pyramid.pyramids.jsonl`).
  This is what `zpa-audit` and `zpa-gate` cost.
- **The chunk probe costs roughly 240–1,900× the header audit's bytes** (0.9–8.1 MiB here) and
  answers a different question: do the chunks that are present hold data?
  On the defective root it reads 0 bytes, because there are no chunks to read;
  the 41 HEADs are its spread candidates confirming that.
- `CHUNK_LEVEL_NO_SAMPLES` on the PHerc1447 volume is a **coverage gap**: one
  sparse level had no stored chunk at any of the 9 spread positions. It is
  not a finding and not evidence of emptiness.
- `reads` can exceed decoded samples: an uncompressed chunk whose 4 KiB prefix
  is all zero is fetched again in full.

## What is and is not measured

- Counts are taken at the store API (`zpa.bench.CountingStore`): one count per
  metadata read, listing, existence probe or chunk read. Retries inside the
  store are not counted separately.
- **Payload bytes are bytes returned to the auditor, not wire bytes.** HTTP
  headers, TLS, and S3 `ListObjects` responses (the 6 listings per root) are
  not included, and s3fs may read ahead more than a ranged read returns.
- Sharded v3 levels are probed by other code paths (volcomp byte ranges on
  `dl.ash2txt.org`, zarr-python windows on S3) that bypass the store API, so
  their probe cost is reported as *not measured*, never as zero.
- Timings are wall-clock from one cloud container to `s3.us-east-1` on
  2026-10-01, single-threaded, one run each. Treat them as order-of-magnitude.
  `dl.ash2txt.org` was not reachable from that container and is not covered.
