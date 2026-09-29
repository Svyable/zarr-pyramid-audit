# S3 open-data bucket audit — 2026-09-29

The first published run of `zarr-pyramid-audit` against the canonical
open-data bucket, `s3://vesuvius-challenge-open-data/`.

## Why

Villa #1760 audited `dl.ash2txt.org` (241 roots, 18 structural defects) but
explicitly did not cover the S3 bucket: *"S3 listing is a natural extension
(the chunk-presence tri-state was designed for it) but is not exercised in
the committed artifacts."* Villa #1892 later ran an ad-hoc header-only S3
pass over the 811 `.zarr` roots in the catalogue's `metadata.json` and found
one header-only surface volume. That script was never published as a tool.

This run closes the loop: the published auditor, pointed at S3, over every
root a crawl can find — not just the ones the catalogue lists.

## Method

Header-only throughout. No chunk bytes downloaded.

1. **Discovery** — `bin/discover_zarr.py --base s3://vesuvius-challenge-open-data/
   --max-depth 10`: breadth-first crawl, 7,487 directory listings, 0 errors,
   **957 Zarr roots** (146 more than the catalogue-based pass — a crawl finds
   what the catalogue misses).
2. **Audit** — `bin/audit_pyramid.py` over all 957 roots: one `.zattrs`/`zarr.json`
   plus one `.zarray`/`zarr.json` per level, plus one listing per level for the
   `LEVEL_NO_CHUNKS` probe. ~5 minutes wall time.

Reproduce:

```bash
git clone <this repo> && cd zarr-pyramid-audit
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # s3fs needed for the s3:// backend
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
python bin/discover_zarr.py --base s3://vesuvius-challenge-open-data/ \
    --max-depth 10 --out-dir tmp/s3
python bin/audit_pyramid.py --base s3://vesuvius-challenge-open-data/ \
    --roots tmp/s3/discover_zarr.roots.jsonl --workers 16 --out-dir tmp/s3audit
```

## Findings

| | |
|---|---|
| roots audited | **957** |
| clean | **956** |
| with structural defects | **1** |
| findings: high / low / info | 6 / 0 / 0 |

The single defective pyramid, all six levels `LEVEL_NO_CHUNKS` (high):

```
PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr
```

Valid `.zarray` at every level, zero chunk objects at any level — every read
returns `fill_value` (0) with no error, an all-zero 116×1940×4620 "surface
volume". Manually re-verified 2026-09-29: each level's listing contains only
its `.zarray`.

**This confirms villa #1892** (filed 2026-09-22 from an ad-hoc S3 pass), which
found the same store. Credit for the original find goes there. What this run
adds: the defect is **still live a week later**, it is the *only* defect in a
crawl-based (not catalogue-based) survey of 957 roots, and the evidence is now
attached to a reproducible tool run instead of a one-off script.

Its two sibling renders of the same segment
(`2.399um-0.22m-78keV-volume-20260309142202.zarr`,
`9.362um-1.2m-113keV-volume-20250804134230.zarr`) are populated and clean —
safe alternatives for anyone who reached for the L1 render.

Also noted: the ten legacy `samples/PHerc0332/volumes/*-masked.zarr` bare
arrays listed in #1892 no longer exist in the bucket (empty listing
2026-09-29) — apparently removed since that issue was filed.

## Zarr v3 on S3

70 of the 957 roots are Zarr v3 (all six-level OME pyramids: ink-detection
outputs on PHercParis4 segments). All 70 audited clean with the v3 header
path. Several v3 roots do not end in `.zarr` and were found only by the
discovery crawl's header test — the catalogue would miss them.

## Code changes in this fork (vs upstream `sgsllc-jr/zarr-pyramid-audit`)

1. **`lib/httpstore.py` — S3 endpoint configurability.** `S3Store` now accepts
   `endpoint_url=` / `region_name=` (or `AWS_ENDPOINT_URL_S3` /
   `AWS_REGION`). Without this, `open_store("s3://...")` used the global
   `s3.amazonaws.com` endpoint, which is unreachable from some networks —
   the S3 backend could not be exercised at all there.
2. **`lib/zarrmeta.py` — v3 bare arrays classified as `BARE_ARRAY`.** A v3
   `zarr.json` with `node_type: "array"` at a root previously fell through
   with `node_kind="unknown"` and was reported as `NOT_A_ZARR_GROUP`
   ("no .zgroup/zarr.json and nothing Zarr-like") — wrong on both counts.
   It is now reported as `BARE_ARRAY` (info) with shape/chunks/dtype, mirroring
   the v2 bare-array path. Before/after on the 8 v3 roots under
   `community-uploads/forrest/tsm/PHerc1667/`: 8× `NOT_A_ZARR_GROUP` →
   8× `BARE_ARRAY` with full array detail.

## Limitations

- Chunk *content* is not checked — a level whose chunks exist but are corrupt
  passes. Same as upstream.
- 6 directories hit the `--max-depth 10` cap; all six are inside the
  `_thumbnails/` webp-thumbnail cache tree, which holds no Zarr data, so no
  roots are expected to be missed there.
- `LEVEL_NO_CHUNKS` relies on the listing showing dotfiles; on S3 the
  tri-state degrades to `unknown` rather than emitting a false finding if a
  listing ever comes back empty.

## Files

- `audit_pyramid.levels.jsonl` — one record per pyramid level (5,348 levels)
- `audit_pyramid.pyramids.jsonl` — one record per pyramid root
- `audit_pyramid.findings.csv` — the 6 findings (reviewable artifact)
- `audit_pyramid.summary.json` — counts by code/severity
- `audit_pyramid.manifest.json` — provenance (argv, host, package versions)
- `discover_zarr.roots.jsonl` / `.dirs.jsonl` / `.manifest.json` — discovery
