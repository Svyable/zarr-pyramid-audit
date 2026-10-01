# Fixture corpus

A compact, versioned set of Zarr fixtures, each isolating **one** property,
with the expected structured output committed next to it. They pin the
evidence contract (missing ≠ empty ≠ zero-filled; UNKNOWN is never clean)
and make any behaviour change show up as a reviewable diff.

Corpus version: **1** · report schema: **1.1.0** ·
42 on-disk cases, 8 replayed-HTTP cases,
19 byte-range cases.

## Layout

| path | what |
|---|---|
| `zarr/<case>.zarr/` | tiny Zarr v2/v3 trees (raw chunks of a few hundred bytes), built by `corpus.py build` |
| `http/<case>.json` | recorded HTTP responses (status + body per path) replayed through the real `HttpStore`: the transport failures a directory tree cannot show |
| `http/range-cases.json` | byte-range and suffix-range responses, including ambiguous and invalid ones, with the exact expected bytes or error |
| `expected/<case>.json` | golden output per case: every finding's code, severity, level and evidence state; per-level evidence; integrity and coverage; gate verdict; recommended consumer verdict; chunk-probe statuses (on-disk cases) |
| `corpus.py` | case definitions, builder, runner and golden projection |

The golden files leave out free-text `detail` strings and environment-specific
values (absolute paths, tool version); everything a consumer branches on is in.

## How it is checked

`tests/test_fixture_corpus.py`:

- every case's computed result equals its golden file;
- every report validates against `src/zpa/data/audit-report.schema.json`;
- the committed trees equal a fresh `corpus.py build` (Blosc chunks compared by payload);
- **transport invariance**: every on-disk case gives the *same* golden result
  when served by Python's `http.server`, an autoindex that ignores `Range`
  headers, through `HttpStore`;
- every check code and chunk-probe code is exercised by at least one fixture
  (three documented exemptions), and every integrity state and consumer
  verdict appears;
- no fixture with UNKNOWN evidence ends up PASS, passes the gate, or defers to quality.

## Use it elsewhere

The trees are plain files. Point any tool at them:

```bash
zpa-gate --base fixtures/zarr --root missing_level.zarr          # exit 1
python -m http.server -d fixtures/zarr 8000 &                     # or over HTTP
zpa-audit --base http://127.0.0.1:8000/ --root clean_v2.zarr --out-dir tmp/fx
```

## Changing it

```bash
python fixtures/corpus.py build      # after editing a builder in corpus.py
python fixtures/corpus.py expected   # after an intentional behaviour change (also rewrites the table below)
git diff fixtures/expected           # review every changed golden
```

A changed golden is a contract change: see "Contract changes" in
[`CHANGELOG.md`](../CHANGELOG.md). Bump `CORPUS_VERSION` when cases are
removed or renamed.

## Cases

| case | property isolated | findings (severity, evidence) | integrity | gate | chunk probe |
|---|---|---|---|---|---|
| `clean_v2` | clean 3-level v2 pyramid; no findings at any severity | — | PASS | pass | populated |
| `clean_v3` | clean 2-level zarr v3 / OME 0.5 pyramid with raw 'bytes' chunks | — | PASS | pass | populated |
| `missing_level` | level 2 declared in multiscales, no header on disk | `LEVEL_MISSING` (high, ABSENT) | FAIL | fail | populated |
| `level_no_chunks` | level 1 header present, zero chunk keys (silent fill_value) | `LEVEL_NO_CHUNKS` (high, ABSENT) | FAIL | fail | populated; `CHUNK_LEVEL_NO_CHUNKS` |
| `level_undeclared` | level directory 3 exists with a header but is not declared | `LEVEL_UNDECLARED` (medium, PRESENT) | WARN | pass | populated |
| `scale_shape_mismatch` | level 1 shape matches neither ceil nor floor of base/2 | `SCALE_SHAPE_MISMATCH` (high, PRESENT) | FAIL | fail | populated |
| `mixed_rounding` | level 1 rounds up (ceil), level 2 rounds down (floor) | `MIXED_ROUNDING` (medium, PRESENT) | WARN | pass | populated |
| `scale_nonmonotonic` | declared scale does not increase from level 1 to level 2 | `SCALE_NONMONOTONIC` (medium, PRESENT) | WARN | pass | populated |
| `dtype_drift` | level 1 is uint16 while level 0 is uint8 | `DTYPE_DRIFT` (high, PRESENT) | FAIL | fail | populated |
| `fill_drift` | level 1 fill_value differs from level 0 | `FILL_DRIFT` (medium, PRESENT) | WARN | pass | populated |
| `compressor_drift` | level 1 is blosc-compressed, levels 0 and 2 are raw | `COMPRESSOR_DRIFT` (low, PRESENT) | PASS | pass | populated |
| `separator_drift` | level 1 uses '/' dimension_separator, others '.' | `SEPARATOR_DRIFT` (high, PRESENT) | FAIL | fail | populated |
| `ndim_drift` | level 1 is 2-D inside a 3-D pyramid | `NDIM_DRIFT` (high, PRESENT) | FAIL | fail | populated |
| `axes_mismatch` | two axes declared for 3-D arrays | `AXES_MISMATCH` (low, PRESENT) | PASS | pass | populated |
| `degenerate_level` | level 1 has a zero extent | `DEGENERATE_LEVEL` (high, PRESENT), `LEVEL_NO_CHUNKS` (high, ABSENT), `SCALE_SHAPE_MISMATCH` (high, PRESENT) | FAIL | fail | populated; `CHUNK_LEVEL_NO_CHUNKS` |
| `chunk_exceeds_shape` | deepest level chunk exceeds its shape on every axis (benign info) | `CHUNK_EXCEEDS_SHAPE` (info, PRESENT) | PASS | pass | populated |
| `physical_scale_unknown` | physical_size explicitly 'unknown', no contradicting claim (info) | `PHYSICAL_SCALE_UNKNOWN` (info, PRESENT) | PASS | pass | populated |
| `physical_scale_contradiction_units` | physical_size 'unknown' but spatial axes declare micrometer units | `PHYSICAL_SCALE_CONTRADICTION` (high, PRESENT) | FAIL | fail | populated |
| `physical_scale_contradiction_scale` | physical_size 'unknown' but level-0 spatial scale is not identity | `PHYSICAL_SCALE_CONTRADICTION` (high, PRESENT) | FAIL | fail | populated |
| `physical_scale_unspecified` | no physical_size marker plus units and a real voxel size: nothing is guessed | — | PASS | pass | populated |
| `ome_version_unmodelled` | declares OME-NGFF 0.6, newer than the audit models: conformance checks skipped (info) | `OME_VERSION_UNMODELLED` (info, PRESENT) | PASS | pass | populated |
| `transform_scale_count` | level 1 declares two scale transforms (spec: exactly one) | `TRANSFORM_SCALE_COUNT` (low, PRESENT) | PASS | pass | populated |
| `transform_arity` | level 1 translation has 2 entries for 3 axes | `TRANSFORM_ARITY` (low, PRESENT) | PASS | pass | populated |
| `axes_invalid` | two axes share the name 'y' | `AXES_INVALID` (low, PRESENT) | PASS | pass | populated |
| `multiscale_empty` | multiscales key present with an empty datasets list | `MULTISCALE_EMPTY` (high, PRESENT) | FAIL | fail | — |
| `not_multiscale` | valid Zarr group that never claims to be a pyramid (info) | `NOT_MULTISCALE` (info, PRESENT) | PASS | pass | — |
| `bare_array` | single-scale v2 array at the root (info) | `BARE_ARRAY` (info, PRESENT) | PASS | pass | — |
| `headerless_chunk_store` | chunk keys present, no .zarray/.zgroup/zarr.json | `HEADERLESS_CHUNK_STORE` (high, PRESENT) | FAIL | fail | — |
| `container_no_group_header` | children are Zarr arrays; no group header at root | `CONTAINER_NO_GROUP_HEADER` (low, PRESENT) | PASS | pass | — |
| `not_a_zarr_group` | directory named *.zarr with nothing Zarr-like inside (info) | `NOT_A_ZARR_GROUP` (info, PRESENT) | PASS | pass | — |
| `root_absent` | requested root does not exist (confirmed absence) | `ROOT_ABSENT` (low, ABSENT) | UNKNOWN | absent | — |
| `malformed_zgroup` | truncated .zgroup JSON | `METADATA_UNREADABLE` (high, PRESENT) | FAIL | fail | — |
| `malformed_zattrs` | valid .zgroup, truncated .zattrs JSON | `METADATA_UNREADABLE` (high, PRESENT) | FAIL | fail | — |
| `malformed_level_header` | level 1 .zarray is truncated JSON | `METADATA_UNREADABLE` (high, PRESENT) | FAIL | fail | populated |
| `present_all_fill` | every chunk is stored but decodes to fill_value 0 | — | PASS | pass | empty; `CHUNK_SAMPLE_ALL_EMPTY` |
| `zero_data_nonzero_fill` | chunks hold zeros but fill_value is 255: zero-filled is data, not empty | — | PASS | pass | populated |
| `nan_fill_all_empty` | float32 chunks all NaN with fill_value "NaN" (v2 string form) | — | PASS | pass | empty; `CHUNK_SAMPLE_ALL_EMPTY` |
| `sparse_level` | only 3 of 8 level-0 chunks stored: missing is not empty | — | PASS | pass | populated |
| `all_fill_nonzero` | every stored byte equals fill_value 255: empty, though no byte is zero | — | PASS | pass | empty; `CHUNK_SAMPLE_ALL_EMPTY` |
| `sparse_unsampled` | one stored chunk in a 64-chunk level, outside every spread sample: a coverage gap | — | PASS | pass | populated; `CHUNK_LEVEL_NO_SAMPLES` |
| `undecodable_codec` | chunks use a codec the probe cannot decode (zstd): reported, never guessed | — | PASS | pass | undecodable; `CHUNK_UNDECODEABLE` |
| `partially_empty` | one populated chunk among seven all-fill ones; the 3-sample probe sees only fill and raises the review flag: a sample is evidence, not exhaustive validation | — | PASS | pass | empty, populated; `CHUNK_SAMPLE_ALL_EMPTY` |
| `http_503_everywhere` | every request answers 503: nothing can be concluded (UNKNOWN, gate fails closed) | `ACCESS_UNKNOWN` (info, UNKNOWN) | UNKNOWN | unreadable | — |
| `http_403_forbidden` | access denied is not absence: 403 stays UNKNOWN | `ACCESS_UNKNOWN` (info, UNKNOWN) | UNKNOWN | unreadable | — |
| `http_429_level` | one level rate-limited: UNKNOWN, never PASS and never LEVEL_MISSING | `ACCESS_UNKNOWN` (info, UNKNOWN) | UNKNOWN | unreadable | — |
| `http_timeout_level` | a level header read times out: UNKNOWN, not missing | `ACCESS_UNKNOWN` (info, UNKNOWN) | UNKNOWN | unreadable | — |
| `http_soft_404_html` | server answers 200 with an HTML error page for .zgroup (soft 404): unreadable metadata, fails closed | `METADATA_UNREADABLE` (high, PRESENT) | FAIL | fail | — |
| `http_listing_405` | no directory listings (405): chunk presence is a coverage gap, not LEVEL_NO_CHUNKS | — | PASS | pass | — |
| `http_listing_hides_header` | listings succeed but never show the array header (dotfiles hidden / empty page): chunk presence unverified, no absence claimed | — | PASS | pass | — |
| `http_empty_zarr_dir` | listing succeeds and is empty, all header probes 404: EMPTY_ZARR_DIR | `EMPTY_ZARR_DIR` (low, ABSENT) | UNKNOWN | absent | — |
