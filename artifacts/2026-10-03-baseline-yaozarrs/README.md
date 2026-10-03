# Baseline comparison, yaozarrs added — 2026-10-03

Adds a third baseline to [`2026-10-01-baseline-comparison`](../2026-10-01-baseline-comparison/)
(left unchanged): [yaozarrs](https://github.com/imaging-formats/yaozarrs)
0.3.2, a pydantic-only OME-NGFF validator. Its `validate_zarr_store()`, which
the `yaozarrs validate` CLI runs, checks the metadata *and* the store
structure: each declared level exists as an array whose dimensionality matches
the axes. That makes it the closest existing tool to ZPA's header audit, so it
is the fairest comparison available.

## 1. The live defect (real data)

```bash
pip install 'yaozarrs[io]'
python artifacts/2026-10-03-baseline-yaozarrs/live_check.py
```

→ [`live_check.log`](live_check.log), anonymous HTTPS to the public bucket:

| root (PHerc0814 surface volumes) | yaozarrs | ZPA |
|---|---|---|
| `1.129um-0.22m-59keV-volume-20260521123630-L1.zarr` (defective) | **accepts** | gate **FAIL**: 6 × `LEVEL_NO_CHUNKS` ([`2026-10-01-gate-proof`](../2026-10-01-gate-proof/)) |
| `2.399um-0.22m-78keV-volume-20260309142202.zarr` (populated sibling) | accepts | gate PASS |
| `does-not-exist.zarr` (positive control) | rejects (`FileNotFoundError`) | — |

The control shows the validator really read the store, so the "accepts" is not
vacuous. Structural validation stops at the level arrays' headers; it does
not check whether any chunk is stored, so the chunkless pyramid passes. The
zarr-python and ome-zarr-models results on the same roots are in the
2026-10-01 artifact.

## 2. The fixture corpus

```bash
pip install ome-zarr-models 'yaozarrs[io]'
python fixtures/compare_baselines.py --out-dir artifacts/2026-10-03-baseline-yaozarrs
```

→ [`comparison.md`](comparison.md), [`comparison.json`](comparison.json).
Same corpus (version 1), same ground truth, same definition of "flagged" as
the 2026-10-01 run; the other rows reproduce it exactly.

| tool | defects flagged | suspicious content flagged | false alarms on valid pyramids | out-of-model nodes identified |
|---|---|---|---|---|
| zarr-python | 8 / 26 | 0 / 3 | 0 / 10 | 1 / 4 |
| ome-zarr-models | 14 / 26 | 0 / 3 | 0 / 10 | 4 / 4 |
| yaozarrs | 13 / 26 | 0 / 3 | 0 / 10 | 4 / 4 |
| ZPA header audit | 25 / 26 | 0 / 3 | 1 / 10 | 4 / 4 |
| ZPA + sampled chunk probe | 26 / 26 | 3 / 3 | 2 / 10 | 4 / 4 |

## Read this before quoting the numbers

- **Same selection bias** as the 2026-10-01 run: the corpus was written
  around ZPA's failure classes. Read it per defect class.
- **yaozarrs vs ome-zarr-models.** They differ on one fixture:
  `dimension_names_missing` (an OME 0.5 array without the required
  `dimension_names`) is rejected by ome-zarr-models and accepted by yaozarrs
  0.3.2. Its structural check did catch `missing_level`, `ndim_drift` and
  `malformed_level_header`, all v0.4 fixtures, although its docstring says
  structural validation supports 0.5 only.
- **What no baseline sees:** chunkless levels, scale/shape mismatches, mixed
  rounding, non-monotonic scales, dtype/fill/separator drift, undeclared level
  directories and contradictory physical-scale metadata. These are the same
  classes as in the 2026-10-01 run; adding a structure-aware validator closed
  none of them.
