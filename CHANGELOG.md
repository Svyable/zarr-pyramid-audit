# Changelog

## Contract changes — the rule

Check codes, severities, the report schema and the recommended consumer
verdicts are an API: [ScrolIQ](https://github.com/Svyable/scrollq) and other
pipelines branch on them (`high` → DO NOT TRAIN). So any change to

- a check code (added, removed, renamed) or its severity,
- `SCHEMA_VERSION` or `src/zpa/data/audit-report.schema.json`,
- the integrity states or `RECOMMENDED_CONSUMER_VERDICT` in `src/zpa/report.py`,

needs, in the same PR:

1. **A migration note** below, under the release it ships in, that says what
   changed, what a consumer must do, and quotes the new
   `contract-fingerprint: <hash>` (`python -c "from zpa.report import
   contract_fingerprint as f; print(f())"`). `tests/test_contract.py` fails
   until the current fingerprint appears in this file.
2. **A fixture update**: a fixture that exercises the new or changed code
   (`fixtures/corpus.py`), and regenerated goldens
   (`python fixtures/corpus.py expected`) whose diff is reviewed in the PR.
   `tests/test_fixture_corpus.py` fails if any check code has no fixture.
3. **Schema version bump** when the report's shape changes: patch for
   documentation, minor for added optional fields or codes, major for removed
   or renamed fields, codes, states or a changed meaning.

## Unreleased

### Contract 1.2.0 — tifxyz surfaces; OME 0.5 dimension_names

`contract-fingerprint: 08f47eac96db`

Minor schema bump (`schema_version` `1.2.0`): a second report kind and new
codes, nothing removed or renamed, the pyramid report's fields unchanged.
Migration notes for consumers:

- **New report kind `"tifxyz"`** from `zpa-tifxyz` /
  `zpa.tifxyz.audit_surface`, validated by
  `src/zpa/data/tifxyz-report.schema.json`. It has the same finding fields,
  evidence states and `integrity` rules as the pyramid report, so an
  existing consumer policy applies unchanged. `validate_report()` picks the
  schema by `kind`; `load_schema(kind)` takes `"pyramid"` (default) or
  `"tifxyz"`.
- **New tifxyz codes** (`contract()["tifxyz_codes"]`), none `high`:
  - medium: `TIFXYZ_META_MISSING`, `TIFXYZ_META_UNREADABLE`,
    `TIFXYZ_CHANNEL_MISSING`, `TIFXYZ_TIFF_UNREADABLE`,
    `TIFXYZ_CHANNEL_SHAPE_MISMATCH`, `TIFXYZ_EMPTY`;
  - low: `TIFXYZ_ABSENT`, `TIFXYZ_META_INCOMPLETE`, `TIFXYZ_SAMPLE_FORMAT`,
    `TIFXYZ_INVALID_MASK_MISMATCH`, `TIFXYZ_NONFINITE`,
    `TIFXYZ_NEGATIVE_COORDINATE`, `TIFXYZ_BBOX_MISMATCH`;
  - info: `TIFXYZ_CONTENT_UNDECODED` (coverage gap), `ACCESS_UNKNOWN`.

  `TIFXYZ_ABSENT` joins `ROOT_ABSENT` / `EMPTY_ZARR_DIR` as "nothing to
  audit": integrity `UNKNOWN`, never `PASS`. Each code is isolated by a
  fixture in `fixtures/surfaces/`.
- **Evidence for the severities**: all 1,539 tifxyz surfaces in the public
  S3 bucket (`artifacts/2026-10-01-s3-tifxyz/`).
  - Header tier: all structurally complete; none of the medium codes fires.
  - Content tier on the 1,391 surfaces with channels ≤ 32 MiB: no empty
    surface, no channel-mask disagreement, no non-finite coordinate.
  - 161 `TIFXYZ_NEGATIVE_COORDINATE`, with metadata that honestly declares
    the extent.
  - 30 `TIFXYZ_BBOX_MISMATCH`: 28 where the `-1` invalid marker leaked into
    the declared bbox minimum (one PHercParis4 batch), and 2 where stored
    points lie outside the declared bbox.

  That is review-grade evidence, not do-not-train evidence, so nothing is
  above medium.
- **New audit code `DIMENSION_NAMES_MISMATCH` (`low`)**: when OME-Zarr ≥ 0.5
  is declared, every v3 array's `dimension_names` must equal the multiscales
  axes names. It cannot fire on the S3 bucket, where every root declares 0.4
  (`artifacts/2026-10-01-s3-conformance/`). Fixture:
  `dimension_names_missing`.
- `zpa-discover` writes `discover_zarr.surfaces.jsonl` (tifxyz surfaces seen
  in listings, at no extra request cost). Existing outputs are unchanged.
- `open_store()` and `LocalStore` accept `os.PathLike`.
- New optional extra `[tifxyz]` (`tifffile`, `imagecodecs`) for the content
  tier on tiled / LZW / predictor TIFFs. The header tier needs neither, and
  neither does CI.

### Evidence and documentation

- `docs/SUBMISSION.md`: submission criteria mapped to the command, file or
  artifact behind each claim, including the known gaps.
- `artifacts/2026-10-01-baseline-comparison/` and
  `fixtures/compare_baselines.py`: zarr-python and ome-zarr-models run on the
  live PHerc0814 defect (the validator accepts it; zarr-python reads all zeros
  without error) and on the fixture corpus, with the selection bias stated.
- Fixture `clean_v3` now carries the `dimension_names` OME-Zarr 0.5 requires.
  ome-zarr-models rejected the old version; ZPA did not, which led to
  `DIMENSION_NAMES_MISMATCH` (contract 1.2.0 below).
- README, dashboard and the September page brought up to date: ScrolIQ's
  fail-closed verdict rules (scrollq#55), the baseline comparison (a new
  dashboard panel generated from `comparison.json`), and the tifxyz survey.
  `docs/september-2026.html` keeps its 2026-09-30 claims and gains a dated
  "post-deadline update" panel.

### Contract 1.1.0 — OME-NGFF conformance codes

`contract-fingerprint: 569547603cf1`

Minor schema bump (`schema_version` `1.1.0`): four codes added, none changed
or removed, no field changes. Migration notes for consumers:

- **New audit codes**, all non-blocking (`integrity` stays `PASS` unless
  something else fires), each isolated by a fixture:
  - `TRANSFORM_SCALE_COUNT` (`low`) — a dataset declares zero or several
    `scale` transforms; NGFF requires exactly one (`transform_scale_count`).
  - `TRANSFORM_ARITY` (`low`) — a `scale`/`translation` length differs from
    the axes count, or the array ndim when no axes are declared
    (`transform_arity`).
  - `AXES_INVALID` (`low`) — duplicate axis names, or typed axes outside
    NGFF's count/order rules (`axes_invalid`).
  - `OME_VERSION_UNMODELLED` (`info`) — a declared NGFF version newer than
    0.5 (or unparseable); the conformance checks above are then skipped
    instead of applying 0.4/0.5 rules to a different model
    (`ome_version_unmodelled`).
  They are `low` deliberately: the known corpus shows none of them, so
  there is no evidence yet that they mean "do not train". Raising any of
  them is a further contract change. Verified live on all 957 S3 roots
  (`artifacts/2026-10-01-s3-conformance/`): 0 conformance findings, every
  root declares OME-NGFF 0.4, and the 2026-09-29 findings are reproduced
  row for row.
- **No existing golden changed.** `TRANSFORM_ARITY` is not reported where the
  *axes list* is the odd one out: if the axes length differs from the array
  ndim (`AXES_MISMATCH`) while the transform matches the array, that is one
  root cause and it is reported once, not once per level. The `axes_mismatch`
  fixture (2 axes on 3-D arrays) therefore keeps its original golden. A
  transform that matches neither the axes nor the array is still flagged.
- **New chunk-probe code** `SHARD_INDEX_CHECKSUM_MISMATCH` (`low`): a
  volcomp shard index whose CRC32C does not match is not sampled (its
  offsets are untrusted); other shards still are. The run summary gains an
  `index_crc` tally separating `verified` from `unchecksummed`, so a clean
  run is only clean where it says `verified`. Shards whose index sits at the
  start (`index_location: start`) are reported `undecodable` rather than
  misread. Not in the report schema (chunk-probe output is a CSV).
- `zpa.chunkscan` now exports `STATUS_CODES` / `FALLBACK_STATUS_CODE`;
  `zpa.scan_empty_chunks.SAMPLE_FINDINGS` / `FALLBACK_FINDING` are derived
  from them for compatibility.

## 0.4.0 — 2026-10-01

Package version 0.4.0 ships report contract (`schema_version`) 1.0.0. The two
are versioned independently: the package version follows features and fixes,
the schema version follows the report's shape and meaning.

### Contract 1.0.0 — first versioned contract

`contract-fingerprint: 63b0a248b758`

Migration notes for consumers:

- **New: `zpa.report`** — `audit_root(store, root)` / `build_report(pm)`
  return a report validated by `zpa/data/audit-report.schema.json`
  (`schema_version` `1.0.0`). Branch on `integrity`
  (`PASS` / `WARN` / `UNKNOWN` / `FAIL`) instead of re-deriving it from raw
  findings. `audit_one`'s return value and finding fields are unchanged.
- **`UNKNOWN` is a distinct state and is never `PASS`.** It covers evidence
  that could not be observed (`ACCESS_UNKNOWN`: timeout, 403, 429, 5xx...)
  and roots with nothing to audit (`ROOT_ABSENT`, `EMPTY_ZARR_DIR`). A
  consumer that only checks for `high`/`medium` severities treats these as
  clean, because `ACCESS_UNKNOWN` is `info` and `ROOT_ABSENT` is `low`.
  Recommended action: DO NOT TRAIN, as `zpa-gate` already fails closed.
- **Gate: absent roots now fail.** `zpa-gate` used to *pass* a root that does
  not exist (or is an empty directory). It now fails it as `GATE_ROOT_ABSENT`
  (`high`, gate-only code). `--allow-absent` restores the old behaviour.
  This invalidated the 2026-09-30 "passes clean sibling" proof (that path does
  not exist); see the erratum in `artifacts/2026-09-30-gate-proof/` and the
  corrected proof in `artifacts/2026-10-01-gate-proof/`.
- **Gate output:** `--out` JSON gains `schema_version`, and each result gains
  `integrity`, `report` (the full audit report) and `below_threshold`.
  Text PASS lines now list below-threshold codes, not only `info` codes.

### Fixed

- Chunk probe: a raw chunk whose bytes are all equal to a **non-zero fill
  value** (e.g. 255) was reported `populated`, because the 4 KiB prefix
  shortcut treated any nonzero byte as data. The shortcut now applies only to
  integer dtypes with a zero fill; everything else is decoded.
- Chunk probe: v2's string fill values `"NaN"`, `"Infinity"` and
  `"-Infinity"` were not recognised, so all-NaN chunks read as `populated`.
- Chunk probe: chunks smaller than the 4 KiB prefix failed the strict
  ranged read and were reported `CHUNK_FETCH_ERROR`; the prefix is now
  clamped to the object size.
- Chunk probe: unsharded v3 levels were addressed with v2 chunk keys (level
  records lacked `zarr_format`) and v3 `bytes`-only chunks were undecodable.
- Volcomp shard probe: shard indexes were fetched with a raw suffix request
  and any 206 body was parsed, even one whose `Content-Range` was missing
  or covered the wrong window. They now go through the store's strict
  `get_suffix` (fail closed → `fetch_error`; 404 → `missing`; 416 →
  `undecodable`), with a strict size-probe fallback for servers that reject
  suffix ranges. The probe no longer uses the HTTP store's private session,
  so it also runs on S3 and local stores. Not re-run live: `dl.ash2txt.org`
  was unreachable from the environment that made this change; behaviour
  against servers that send valid `Content-Range` headers is unchanged.
- The committed campaign numbers are unaffected by the probe fixes: every
  uncompressed level in `artifacts/` is an integer dtype with fill `0`.

### Added

- `fixtures/`: versioned fixture corpus (one property per case) with golden
  structured outputs, replayed HTTP failure cases and byte-range edge cases.
- `LocalStore`: `open_store()` accepts `file://` and plain paths, so a
  staging tree can be gated before upload.
- `zpa-bench`: per-root latency, store calls and payload bytes for the header
  audit and the chunk probe (`artifacts/2026-10-01-bench/`).
- `examples/`: GitHub Actions gate job, local preflight script, Python API
  example. `docs/INTEGRATION.md`: integration guide and ScrolIQ surface.

### Documentation

- README leads with what ZPA audits, emits and cannot certify; adds
  "Reproduce in 60 seconds", Limitations, the ScrolIQ integration surface and
  the audit-cost benchmark table.
- `docs/september-2026.html`: dated correction of the gate-proof claim (the
  "clean sibling" path does not exist); the reproduce block now names the
  populated sibling `2.399um-0.22m-78keV-volume-20260309142202.zarr`.
- `artifacts/2026-09-30-gate-proof/README.md`: erratum, logs kept unchanged.
