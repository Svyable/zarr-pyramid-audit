# Baseline comparison — 2026-10-01

What do the tools people already use say about the defects ZPA targets? Two
baselines, run on the same inputs as ZPA:

- **zarr-python 3.1.6**: open the group and read every declared level, the
  way a data loader does. The only signal it can give is raising an error.
- **ome-zarr-models 1.7**: the OME-NGFF 0.4/0.5 metadata validator. It
  accepts or rejects.

## 1. The live defect (real data)

`live_check.py` → `live_check.log`, against public S3 (anonymous):

| root (PHerc0814 surface volumes) | ome-zarr-models | zarr-python, level 5, 64³ window | ZPA |
|---|---|---|---|
| `1.129um-0.22m-59keV-volume-20260521123630-L1.zarr` (defective) | **accepts** (valid `Image`) | **249,856 voxels, all zero, no error** | gate **FAIL**: 6 × `LEVEL_NO_CHUNKS` ([`2026-10-01-gate-proof`](../2026-10-01-gate-proof/)) |
| `2.399um-0.22m-78keV-volume-20260309142202.zarr` (populated sibling) | accepts | 233,472 voxels, 176,423 nonzero | gate PASS |

Both baselines treat the defective pyramid as healthy. The metadata is
spec-valid, and the missing chunks read as `fill_value`. This is the defect
class ZPA exists for, independently reported as
[villa #1892](https://github.com/scrollprize/villa/issues/1892).

## 2. The fixture corpus (one property per case)

```bash
pip install ome-zarr-models
python fixtures/compare_baselines.py --out-dir artifacts/2026-10-01-baseline-comparison
```

→ `comparison.md` (per-fixture table) and `comparison.json`. Each fixture's
ground truth is assigned in `GROUND_TRUTH` from what it was **built** to
contain, not from ZPA's output. "Flagged" means the tool gave its user any
signal: it raised, it rejected, or ZPA reported a non-info code or a
non-PASS integrity.

| tool | defects flagged | suspicious content flagged | false alarms on valid pyramids | out-of-model nodes identified |
|---|---|---|---|---|
| zarr-python | 8 / 26 | 0 / 3 | 0 / 10 | 1 / 4 |
| ome-zarr-models | 14 / 26 | 0 / 3 | 0 / 10 | 4 / 4 |
| ZPA header audit | 25 / 26 | 0 / 3 | 1 / 10 | 4 / 4 |
| ZPA + sampled chunk probe | 26 / 26 | 3 / 3 | 2 / 10 | 4 / 4 |

What only ZPA reports here: chunkless levels (silent zeros), scale/shape
mismatches, mixed rounding, non-monotonic scales, dtype/fill/separator
drift, undeclared level directories, contradictory physical-scale metadata,
and stored-but-empty chunks (the probe, including non-zero and NaN fill
values).

## Read this before quoting the numbers

- **Selection bias.** The corpus was written by the ZPA authors around ZPA's
  failure classes, so the ZPA columns are expected to be high. The fair
  reading is per row, not per total: which *defect classes* each tool can see
  at all. The live result in section 1 is the evidence that does not depend
  on how the fixtures were chosen.
- **Where a baseline did better, and what changed.** ome-zarr-models enforces
  spec rules ZPA did not check. Our first `clean_v3` fixture lacked the
  `dimension_names` that OME-Zarr 0.5 requires: the validator rejected it and
  ZPA did not. The fixture was fixed, and ZPA gained
  `DIMENSION_NAMES_MISMATCH` (`low`). The new `dimension_names_missing`
  fixture is now flagged by both tools. The validator still covers the full
  NGFF spec, which ZPA does not attempt, and it rejects every non-pyramid
  node, which is correct for its purpose. The two tools are complementary:
  run the validator for spec compliance and ZPA for structural integrity.
- **ZPA's own false alarms.**
  - `compressor_drift` is legal; ZPA reports it as `low`, and integrity stays
    `PASS`.
  - `partially_empty` has one populated chunk among seven empty ones. The
    3-sample probe raises the `medium` review flag. That is the documented
    sampling limitation: a sample is evidence, not exhaustive validation.
- **The one defect the header audit misses**, `undecodable_codec` (bytes that
  do not match the declared codec), needs chunk reads. The probe reports it
  as `CHUNK_UNDECODEABLE`. zarr-python also catches it, by raising on read.
- **Not compared.** The replayed-HTTP failure cases (503/403/429, timeouts,
  invalid ranges) exist only as recorded responses for `HttpStore`.
  [Bullo27/scroll-data-audit](https://github.com/Bullo27/scroll-data-audit)
  was not re-run here; the README's earlier cross-validation against it
  stands.
