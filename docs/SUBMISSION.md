# Submission criteria → evidence

A reviewer's map: each requirement, the claim we make, and the command,
file or artifact that backs it. Every number below comes from a committed
artifact; follow the link, rerun the command.

**In one line:** zarr-pyramid-audit (ZPA) finds OME-Zarr pyramids in the
Vesuvius open data whose metadata promises data that is not there or not
what it claims to be. On the live defects, the standard tools do not raise
an error and the standard validator passes the metadata. ZPA turns the
finding into a fail-closed CI gate, and emits versioned, machine-readable
evidence that downstream tools consume.

---

## 1. Problem identification and solution

### Addresses a specific challenge using Vesuvius Challenge scroll data

| claim | evidence |
|---|---|
| A confirmed silent-zeros defect is live in the official S3 bucket: a PHerc0814 surface volume whose 6 levels all have valid headers and zero chunks | [`artifacts/2026-09-29-s3/SILENT_ZEROS.md`](../artifacts/2026-09-29-s3/SILENT_ZEROS.md); re-verified [`2026-09-30-s3-reverify`](../artifacts/2026-09-30-s3-reverify/); independently confirms [villa #1892](https://github.com/scrollprize/villa/issues/1892) |
| Audited the whole S3 bucket: 957 roots, 956 clean, 1 defective | [`artifacts/2026-09-29-s3/`](../artifacts/2026-09-29-s3/); reproduced row for row on 2026-10-01 with the conformance checks on, [`2026-10-01-s3-conformance`](../artifacts/2026-10-01-s3-conformance/) |
| Audited all 241 `dl.ash2txt.org` roots: 18 defective pyramids. A 20-day re-run found 0 of them fixed | [`artifacts/2026-09-09/`](../artifacts/2026-09-09/), [`2026-09-29-dl-regression`](../artifacts/2026-09-29-dl-regression/) |
| All 1,539 tifxyz surface patches in the S3 bucket audited. All are structurally complete. 161 have points outside any CT volume (up to 39.7% of a surface); 30 declare a bbox that disagrees with their stored coordinates (28 with the `-1` marker leaked into the minimum, 2 with points outside the declared box) | [`artifacts/2026-10-01-s3-tifxyz/`](../artifacts/2026-10-01-s3-tifxyz/) |
| The dl findings were filed upstream on 2026-09-10 as villa #1755–#1760 | [`issues/README.md`](../issues/README.md): drafts, repro commands and issue links |
| Sampled chunk-content probes across both hosts: 4,355 populated samples in four campaigns; 7 all-empty levels, all in one dev mesh derivative (`other/dev/meshes/…`, medium, human review) | README "Latest results" table → `artifacts/2026-09-30-{s3-chunkscan,s3-chunkscan-v3,dl-volcomp-probe,dl-v2-probe}/` |

### Clear implementation path and a demonstration of its use

- **Pipeline:** `zpa-discover` (find roots) → `zpa-audit` (header-only, a few
  KB per pyramid) → `zpa-gate` (fail-closed CI gate) → `zpa-scan-chunks`
  (sampled content probe). Each stage is a separate command with its own
  outputs; see the Tools table in the [README](../README.md#tools).
- **60-second demo** against public data, with the expected output committed:
  [README "Reproduce in 60 seconds"](../README.md#reproduce-in-60-seconds) →
  [`artifacts/2026-10-01-gate-proof/`](../artifacts/2026-10-01-gate-proof/).
  On the defective root the gate exits 1; on its populated sibling it exits 0;
  on a path that does not exist it exits 1.
- **Offline demo:** the same command against the committed
  [fixture corpus](../fixtures/README.md); no network needed.
- **Running in CI today:** `.github/workflows/audit.yml` exercises a gate pass,
  a gate rejection and a chunk probe against public S3 on every push and
  weekly.

### Significant advantages over existing solutions

[`artifacts/2026-10-01-baseline-comparison/`](../artifacts/2026-10-01-baseline-comparison/)
runs the tools people already use on the same inputs:

| on the live PHerc0814 defect | result |
|---|---|
| zarr-python (read level 5) | returns 249,856 voxels, **all zero, no error** |
| ome-zarr-models 1.7 (OME-NGFF validator) | **accepts** it as a valid `Image` |
| yaozarrs 0.3.2 (NGFF metadata + structure, [2026-10-03](../artifacts/2026-10-03-baseline-yaozarrs/)) | **accepts** it |
| ZPA | gate **FAIL**, 6 × `LEVEL_NO_CHUNKS` (high) |

On the 43 on-disk fixtures, ZPA's header audit flags 25 of the 26 built-in
defects; zarr-python flags 8, ome-zarr-models 14 and yaozarrs 13. The artifact README
states the selection bias: the corpus was built around ZPA's failure classes.
It also says where the validator did better: it caught a missing OME 0.5
`dimension_names` that ZPA missed, which led to ZPA's
`DIMENSION_NAMES_MISMATCH` check. The validator still covers the full NGFF
spec; ZPA does not attempt to.

Other advantages, each backed by an artifact or a test:

- **Cheap enough for a whole corpus:** under 9 KiB and 1.5–2.3 s per pyramid
  on the benchmarked S3 roots, independent of array size ([`2026-10-01-bench`](../artifacts/2026-10-01-bench/)).
- **No false "clean" on failed reads:** a timeout, 403, 429 or 5xx stays
  `UNKNOWN` and is never reported as clean or as missing
  (`tests/test_evidence_semantics.py`, fixture cases `http_*`).
- **Missing ≠ empty ≠ zero-filled:** each is distinguished, and pinned by
  fixtures (`sparse_level`, `present_all_fill`, `zero_data_nonzero_fill`,
  `all_fill_nonzero`, `nan_fill_all_empty`).
- **Cross-validated:** on the 64 roots that
  [Bullo27/scroll-data-audit](https://github.com/Bullo27/scroll-data-audit)
  also covers, both tools agree. Every ZPA defect is in the 177 roots that
  tool does not cover (README "Original baseline").

## 2. Documentation

| need | where |
|---|---|
| What it is, what it cannot certify, how to run it | [README](../README.md): lead claim, Reproduce in 60 seconds, Tools, Check codes, Usage, [Limitations](../README.md#limitations) |
| Integrating it into a pipeline | [`docs/INTEGRATION.md`](INTEGRATION.md): recipes, report semantics, ScrolIQ surface |
| Every check code and its severity | README "Check codes" (test-enforced equal to the code) |
| Surface-evidence protocol | [`docs/surface-depth-profile.md`](surface-depth-profile.md) |
| What each fixture isolates, with expected results | [`fixtures/README.md`](../fixtures/README.md) (table generated from the goldens) |
| How results are produced | a README in every `artifacts/<date>-*/` giving the exact command |
| Contract changes and migration notes | [`CHANGELOG.md`](../CHANGELOG.md) |
| Contributing and accuracy policy | [`.github/CONTRIBUTING.md`](../.github/CONTRIBUTING.md), README "Accuracy policy" |
| Public dashboard | <https://svyable.github.io/zarr-pyramid-audit/>, generated from `artifacts/` |

### Usage examples

- Every command in the README Usage section. `tests/test_docs_consistency.py`
  checks that every documented flag exists.
- [`examples/`](../examples/): a GitHub Actions gate job, a local preflight
  script and a Python API example. All three run in the test suite against
  the fixture corpus (`tests/test_integration_surface.py`).

## 3. Technical integration

### Accepts standard community formats

| format | status |
|---|---|
| OME-Zarr multiscale pyramids, Zarr **v2** (`.zgroup`/`.zattrs`/`.zarray`) and **v3** (`zarr.json`), OME-NGFF 0.4 and 0.5 | **audited**; newer versions are reported as `OME_VERSION_UNMODELLED` instead of being judged by the wrong rules |
| Bare Zarr arrays (v2/v3) | **recognised** (`BARE_ARRAY`) |
| v3 `sharding_indexed` with volcomp inner chunks (the `dl.ash2txt.org` scroll volumes) | **probed** by decoding over HTTP byte ranges, with shard-index CRC32C verification |
| Raw, Blosc and `bytes` chunks | **decoded** by the probe; other codecs are reported `CHUNK_UNDECODEABLE`, never guessed |
| Stores: `https://` autoindex, `s3://` (anonymous), `file://` or a local path | **all**, same evidence semantics |
| tifxyz quadmeshes (`meta.json` + `x/y/z.tif`, classic TIFF or BigTIFF, uncompressed or tiled/LZW/predictor) | **audited** by `zpa-tifxyz`: structure from TIFF headers via strict range reads; coordinates with `--content`. All 1,539 public S3 surfaces surveyed ([`2026-10-01-s3-tifxyz`](../artifacts/2026-10-01-s3-tifxyz/)); `zpa-discover` lists them in `discover_zarr.surfaces.jsonl` |
| Triangular meshes | **not audited by ZPA.** Mesh and winding audits live in the companion [ScrolIQ](https://github.com/Svyable/scrollq) |

### Maintains consistent output formats

- One versioned JSON report per root or surface (`schema_version` 1.2.0),
  validated by
  [`audit-report.schema.json`](../src/zpa/data/audit-report.schema.json) (Zarr
  roots) or [`tifxyz-report.schema.json`](../src/zpa/data/tifxyz-report.schema.json)
  (surfaces). Both share the finding fields, evidence states and integrity
  rules, and both ship in the wheel.
- The contract (codes, severities, integrity states, recommended verdicts)
  is fingerprinted. `tests/test_contract.py` fails until a change carries a
  migration note.
- Expected outputs for all 67 fixture cases are committed: 43 on-disk Zarr,
  8 replayed HTTP and 16 tifxyz surfaces. Any behaviour change shows up as a reviewable diff
  (`tests/test_fixture_corpus.py`).
- Every CLI run writes CSV/JSONL plus a provenance manifest and never
  overwrites an earlier output.

### Designed for modular integration

- **Python API:** `zpa.report.audit_root(store, root)` returns the schema'd
  report. `open_store`, `read_pyramid`, `audit_one` and `zpa.volcomp` are a
  pinned public surface ([INTEGRATION.md](INTEGRATION.md#scroliq-integration-surface)).
- **CLI per stage:** each `zpa-*` command reads and writes plain files, so
  stages compose in shell or CI.
- **Used downstream today:** ScrolIQ's per-volume verdict calls
  `zpa.report.audit_root` and applies `RECOMMENDED_CONSUMER_VERDICT`
  (scrollq#55), and its `scroliq-provenance` gate requires a ZPA audit
  record for the exact CT volume (README, "How this fits with ScrolIQ").
- **CI:** a copy-paste gate job, plus `--format github` annotations.

## Known gaps (stated, not hidden)

- `dl.ash2txt.org` was unreachable from the environment that produced the
  2026-10-01 runs. The dl campaigns are dated 2026-09-09 to 2026-09-30, and
  the volcomp CRC32C check has not been run on live shards.
- Triangular meshes are not audited by ZPA (see the table above). The tifxyz
  content tier was run on surfaces whose channels are ≤ 32 MiB (1,391 of
  1,539); the other 148 have header-tier evidence only, reported as a
  coverage gap. `TIFXYZ_NEGATIVE_COORDINATE` catches geometry below a
  volume's grid; overruns past its top need the target volume's shape and
  are not checked yet.
- The sampled probe is evidence, not exhaustive validation (README
  Limitations).
- ScrolIQ adopted the fail-closed verdict mapping
  ([Svyable/scrollq#55](https://github.com/Svyable/scrollq/pull/55), merged).
  It pins this repo at `e473afd`, which predates the tifxyz report, so
  ScrolIQ does not consume surface reports yet
  ([INTEGRATION.md](INTEGRATION.md#scroliq-integration-surface)).

The October 2026 plan turns these gaps into goals, each with its exit
evidence: [`october-2026.html`](https://svyable.github.io/zarr-pyramid-audit/october-2026.html).
