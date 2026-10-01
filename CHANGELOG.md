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

### Evidence and documentation

- `docs/SUBMISSION.md`: submission criteria mapped to the command, file or
  artifact behind each claim, including the known gaps.
- `artifacts/2026-10-01-baseline-comparison/` and
  `fixtures/compare_baselines.py`: zarr-python and ome-zarr-models run on the
  live PHerc0814 defect (the validator accepts it; zarr-python reads all zeros
  without error) and on the fixture corpus, with the selection bias stated.
- Fixture `clean_v3` now carries the `dimension_names` OME-Zarr 0.5 requires.
  ome-zarr-models rejected the old version; ZPA does not check this, and no
  ZPA golden changed.

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
- **Existing golden changed:** `axes_mismatch` (2 axes on 3-D arrays) now
  also reports `TRANSFORM_ARITY` on each level, because its 3-entry scales
  disagree with its 2 axes. Integrity is unchanged (`PASS`).
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
