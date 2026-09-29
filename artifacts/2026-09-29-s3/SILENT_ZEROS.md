# Silent zeros, proved — 2026-09-29

The submission's central claim is that header-only pyramid levels are
*silent* corruption: valid headers, no chunks, reads return fill value
with no error. This note replaces inference with a performed read.

## The read

Opened the defective S3 level directly with zarr-python (s3fs, anonymous):

```
root:  PHerc0814/segments/20260226123353-auto_grown_20260226123353106/
       surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr
level 0: shape (116, 1940, 4620), chunks (116, 128, 128), fill_value 0
read [0:256, 0:256, 0:256] -> returned WITHOUT ERROR, all zeros, 0 nonzero voxels
read [0:116, 0:1940, 0:4620] (full extent) -> all zeros
```

Control — a known-good volume, same bucket, same API:

```
root:  PHerc0814/volumes/20260309142202-2.399um-0.2m-78keV-masked.zarr
level 5, region [0:128, 384:512, 128:256] -> 64,498 nonzero voxels
```

No exception, no warning, no partial-read signal. A downstream pipeline
consuming reduced levels gets a plausible all-zero volume and proceeds.

## Isolated to one run, not systematic

19 copies of the defective stem (`1.129um-0.22m-59keV-volume-20260521123630-L1.zarr`)
exist across segment runs in the bucket. Exactly **one** is defective — the
`20260226123353` run. The other 18 are clean and populated, as are the 19
copies each of the sibling renders (`2.399um-0.22m-78keV-volume-20260309142202.zarr`,
`9.362um-1.2m-113keV-volume-20250804134230.zarr`). One pipeline run produced
a header-only pyramid; the tooling around it never noticed.

## The same failure class on dl.ash2txt.org (still live)

`LEVEL_NO_CHUNKS` findings in the 2026-09-09 audit, confirmed unchanged in
the 2026-09-29 regression re-audit:

- `community-uploads/bruniss/labels/surfaces/archive/1-voxel-sheet_slices-closed.zarr`
  — levels 1–5 header-only (5 of 6). Full-res level 0 exists; every reduced
  level silently reads as zero. This is the exact access pattern ink
  detection uses.
- `other/dev/inked_zarrs/3336_predictions.zarr` — all 6 levels header-only.
  An ink-prediction volume that reads as entirely empty.
