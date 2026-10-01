# tifxyz surface audit — S3 bucket, 2026-10-01

Every tifxyz surface patch in `s3://vesuvius-challenge-open-data`, found by
`zpa-discover` and audited by `zpa-tifxyz` with both tiers.

```bash
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
zpa-discover --base s3://vesuvius-challenge-open-data/ --max-depth 10 --workers 16 --out-dir tmp/disc
zpa-tifxyz --base s3://vesuvius-challenge-open-data/ \
  --roots tmp/disc/discover_zarr.surfaces.jsonl \
  --content --max-content-bytes 33554432 --workers 16 \
  --out-dir artifacts/2026-10-01-s3-tifxyz
python artifacts/2026-10-01-s3-tifxyz/summarize.py     # every number below
```

The content tier needs `pip install 'zarr-pyramid-audit[tifxyz]'` (tifffile)
for the tiled/LZW surfaces in this bucket.

Files:
- `discover_zarr.surfaces.jsonl` and `discover_zarr.manifest.json`: the
  surface list and its crawl. The same crawl found the same 957 Zarr roots
  as 2026-09-29.
- `tifxyz.reports.jsonl`: one schema-versioned report per surface.
- `tifxyz.findings.csv`, `tifxyz.summary.json`, `tifxyz.manifest.json`.
- `enumerate.py`: the earlier name-based enumeration. It found 1,458 of the
  1,539 surfaces; the 81 it missed are directories that hold `x/y/z.tif`
  without a `.tifxyz` name (76 under `PHerc1203/segments/raw/`).

## Result

- 1,539 surfaces discovered (857 named `*.tifxyz`, 682 detected by their
  `x/y/z.tif` files).
- **1,539 / 1,539 integrity `PASS`**. Header tier: none of the
  medium-severity codes fired. Every surface has a readable `meta.json` and
  three float TIFF channels on one grid.
- Content tier ran on **1,391** surfaces (1,046 decoded built-in, 345 via
  tifffile). The other **148** have a channel over the 32 MiB cap: header
  evidence only, reported as `TIFXYZ_CONTENT_UNDECODED` (a coverage gap, not
  a pass).
- No empty surface, no channel disagreeing on the `-1` marker, no NaN/inf
  coordinate. Valid-point fraction: 0.020–0.998, median 0.760.

| code | surfaces | what it means here |
|---|---|---|
| `TIFXYZ_NEGATIVE_COORDINATE` | 161 | valid points below 0 on some axis: outside the voxel grid of any OME-Zarr volume |
| `TIFXYZ_CONTENT_UNDECODED` | 148 | coverage gap (size cap) |
| `TIFXYZ_BBOX_MISMATCH` | 30 | declared bbox disagrees with the stored coordinates |

### `TIFXYZ_NEGATIVE_COORDINATE` — 161 surfaces

- **Where.** Mostly final registered surfaces: 143 of the 709
  content-checked `*.tifxyz`, against 18 of the 601 `tifxyz_*`
  intermediates and 0 of the 81 file-detected ones. By scroll: PHerc0139 83,
  PHercParis4 54, PHerc1667 18, PHerc0500P2 3, PHerc0841 2, PHerc0814 1.
- **Which axis.** Mostly `z`: z 131, y 22, y/z 4, x/z 3, x 1.
- **How much.** Median 4.5% of a surface's valid points, maximum 39.7%.
- **The metadata is honest.** In all 161 the declared bbox already shows the
  negative extent. This is geometry that runs off the start of the scan, not
  metadata contradicting data.
- **Worked example.** `PHerc0139/segments/20250108000001-w026_2025010854/mesh/20250108000001-on-20250820105138-2.403um.tifxyz`
  is registered onto volume `20250820105138`. That volume's L0 is z × y × x =
  19393 × 26105 × 26105, with an identity scale and no translation. The
  surface's x (7965–17038) and y (9345–18001) lie inside the grid. Its z
  spans −5859 to 21217, past **both** ends of the 0–19392 slab: 352,980 of
  1,782,040 valid points are below 0, and more lie above the top. Any render
  from that volume has no CT data for that part of the surface.
- **What the check does not do.** It catches only the lower bound, which is
  provable without knowing the target volume. Catching overruns past the top
  of the volume needs that volume's shape. That is a follow-up: resolve the
  `-on-<volume id>-` name to `volumes/<id>-*.zarr`.

### `TIFXYZ_BBOX_MISMATCH` — 30 surfaces, two causes

- **28 loose boxes, the `-1` marker leaked in.** All are PHercParis4
  `tifxyz_original` intermediates from one batch (segments
  20260701183124–183151). The declared minimum is exactly `-1` on axes where
  no stored point is that low: the bbox was computed including invalid cells.
  The box is too large, so nothing is lost by cropping to it.
- **2 with stored points outside the declared box**, so cropping to the bbox
  would drop geometry:
  - `PHerc0139/segments/20260130000001-w030_202601301912/mesh/intermediate/tifxyz_original`:
    2,375 of 1,664,805 valid points. Checked independently with tifffile:
    250 of them lie up to ~2,000 voxels below the declared x minimum.
  - `PHercMAN5/segments/20260321025901-MAN5_outer_3/mesh/intermediate/tifxyz_flattened`:
    755 points (stored z max 29071.6 against a declared 28674.7).

All findings are `low`: review-grade evidence, not do-not-train evidence.
Nothing here justifies a `high` code (AGENTS.md lesson 5).

## Reproducibility

Two earlier full runs over the 1,458 name-enumerated surfaces gave identical
integrity, coverage and `TIFXYZ_BBOX_MISMATCH` results. Those runs used code
from before `TIFXYZ_NEGATIVE_COORDINATE` existed. This run, with the shipped
code, adds the 81 file-detected surfaces; none of them has a finding.
