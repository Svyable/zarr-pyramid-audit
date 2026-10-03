# zarr-pyramid-audit

Read-only integrity auditing for OME-Zarr multiscale pyramids, and for the tifxyz surface patches
segmented from them, served over HTTP, S3 or a local directory.

> **Fork lineage.** This repository is based on the original [`sgsllc-jr/zarr-pyramid-audit`](https://github.com/sgsllc-jr/zarr-pyramid-audit) (MIT), which established the header-first, read-only OME-Zarr auditing approach and the original `dl.ash2txt.org` campaign. The Svyable fork's claim is the extension: versioned evidence contracts and gating, chunk-content / volcomp support, TIFXYZ surface auditing, expanded S3 and Grand Prize preflight campaigns, validator comparisons, and downstream ScrolIQ integration. See [fork scope and attribution](docs/FORK_SCOPE.md).


**What it audits, what it emits, what it cannot certify.** ZPA checks whether a pyramid is what its
metadata says it is: every declared level present and readable, shapes consistent with the declared
scales, dtype/fill/codec/separator consistent across levels, chunk keys actually stored, physical-scale
claims not self-contradictory. A sampled probe also checks whether stored chunks hold data. It emits
evidence, not verdicts: a [versioned JSON report](docs/INTEGRATION.md#the-report-schema-1x) per
root, with every finding's code, severity and the evidence state it rests on (`PRESENT` / `ABSENT` /
`UNKNOWN`), an integrity summary (`PASS` / `WARN` / `UNKNOWN` / `FAIL`), a canonical source-attestation hash of the metadata semantics actually audited, and a fail-closed CI gate.
It **cannot** certify that voxels are semantically correct, that a sampled probe saw every chunk, or
that data it could not read is fine. Unreadable evidence stays `UNKNOWN` and is never reported as
clean. See [Limitations](#limitations).

**Reviewing a submission?** Start with the [2027 Grand Prize integrity map](https://svyable.github.io/zarr-pyramid-audit/grand-prize-readiness.html), which separates what ZPA can prove from what remains the responsibility of the unrolling and ink pipeline. [`docs/SUBMISSION.md`](docs/SUBMISSION.md) maps each Progress Prize criterion to the command
or artifact behind it, including how ZPA compares with zarr-python and the OME-NGFF validator on the
same live defect ([`artifacts/2026-10-01-baseline-comparison/`](artifacts/2026-10-01-baseline-comparison/)). October's goals, each with the evidence that will count as done, are on
[`docs/october-2026.html`](https://svyable.github.io/zarr-pyramid-audit/october-2026.html).

## Reproduce in 60 seconds

One public store, one expected output
([`artifacts/2026-10-01-gate-proof/`](artifacts/2026-10-01-gate-proof/)):

```bash
pip install git+https://github.com/Svyable/zarr-pyramid-audit.git
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com   # anonymous, no credentials
zpa-gate --base s3://vesuvius-challenge-open-data \
  --root PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr
# expected: FAIL, 6 x [high] LEVEL_NO_CHUNKS (levels 0-5), exit 1
#           (artifacts/2026-10-01-gate-proof/gate-rejects-defective.log)
```

For a prize-eligible CT source, the gate can also fail closed on a wrong-resolution
substitution. Supply the exact eligible level-0 voxel size; ZPA converts declared
spatial units to micrometers and requires every spatial axis to match:

```bash
zpa-gate --base s3://vesuvius-challenge-open-data \
  --root <eligible-volume>.zarr \
  --expected-voxel-size-um 9.362
# mismatch or unprovable physical scale => GATE_VOXEL_SIZE_MISMATCH/UNKNOWN, exit 1
```

This fence is opt-in because generic OME-Zarr auditing must not guess which
physical resolution a caller intended.

Offline, from a checkout, against the [fixture corpus](fixtures/README.md):

```bash
zpa-gate --base fixtures/zarr --root clean_v2.zarr --root missing_level.zarr
# expected: PASS clean_v2.zarr, FAIL missing_level.zarr ([high] LEVEL_MISSING level=2), exit 1
```

**[Live data-health dashboard](https://svyable.github.io/zarr-pyramid-audit/)** — the public,
visual summary generated from the committed audit artifacts. The deployable source lives in
[`docs/`](docs/); pull requests verify that the generated dashboard is current before merge.

Built to audit [`dl.ash2txt.org`](https://dl.ash2txt.org/) and the
`s3://vesuvius-challenge-open-data` bucket (the Vesuvius Challenge / Scroll Prize data hosts), but
nothing in it is Vesuvius-specific: point `--base` at any store that exposes a directory autoindex
(or an `s3://` bucket) and it works.

**Part of a two-repo data-quality suite.** This repo answers *is the data what its metadata says it
is?* ("don't train on lies"). Its companion, [ScrolIQ](https://github.com/Svyable/scrollq), answers
*where is the bottleneck, and what is worth doing next?* ("find the bottleneck"). They are
independent tools that compose into one verdict per volume — see
[How this fits with ScrolIQ](#how-this-fits-with-scroliq).

## The failure class this exists to find

Every consumer that is not doing full-resolution work reads a **reduced** level. Viewers navigate at
level 3–5, registration and QC run at level 2, and several published models train on a specific
level. A pyramid level that is absent, mis-declared, or generated with a different convention from
its siblings **does not raise an error anywhere** — it returns plausible-looking voxels.

That is the entire point. These defects are invisible to the tools people actually use:

- A level declared in `multiscales` but missing from the server → 404, or silently `fill_value`.
- A level with a valid `.zarray` **and no chunks at all** → reads return `fill_value` everywhere,
  no error, no warning, no way to tell it from real data without counting keys.
- A `scale` transform that contradicts the array's own shapes → coordinates off by 32× on one axis.
- Chunk files with no header → undecodable, but the directory looks populated.

Checks are **header-only by default**: a pyramid is judged from its `.zattrs` plus one `.zarray` per
level — a few KB regardless of array size — so a whole corpus can be audited without downloading it.

## Design notes worth knowing

**The header-only audit does not use `zarr`.** `zpa-discover`, `zpa-audit` and `zpa-gate` parse
`.zattrs` / `.zarray` / `zarr.json` directly. This is deliberate: a store that `zarr.open()` refuses
to open is exactly the kind of defect the tool needs to *report*, not crash on. Only the
chunk-content probe and the surface tools import `zarr` (it is a declared dependency for them).

**Absence is only ever inferred from positive evidence.** The chunk-presence check
(`LEVEL_NO_CHUNKS`) trusts a directory listing to prove a level is empty *only* if that listing
demonstrably shows a file already known to exist (the header just read). On a store with no
autoindex, or with dotfiles hidden, the result degrades to `unknown` and **no finding is emitted**.
A tri-state (`True` / `False` / `None`), never a boolean. This is what keeps the check portable to
the S3 mirror instead of flagging every level there.

**Metadata access has the same evidence contract.** Header reads and directory listings record
`PRESENT`, `ABSENT`, or `UNKNOWN`. A confirmed 404 can support an absence finding; a timeout,
403, 429, 5xx, unsupported listing, or connection failure cannot. Malformed JSON is separately
reported as `METADATA_UNREADABLE`. Pyramid and level records retain these states so downstream
analysis can distinguish a negative observation from an observation that could not be made.

**Read-only by construction.** The HTTP store class has no write path.

**Reproducible.** Every run writes a manifest with argv, cwd, host, platform, interpreter, package
versions, counters, and output inventory. Outputs are never silently overwritten — an existing file
is backed up to `<name>.<timestamp>.bak` first, so a partial rerun can never be mistaken for a
complete one.

**Severity is honest.** `info` codes describe what a node *is* (a bare array, a non-multiscale
group) and are never counted as defects.

## Tools

| tool | what it does | cost |
|---|---|---|
| `zpa-discover` | Crawls a store's autoindex and finds every Zarr root. Prunes chunk trees, `.tifxyz` leaves, coordinate and segment directories — but runs a Zarr-header test *before* every prune rule, so a heuristic can never discard a real root. | listings only |
| `zpa-audit` | 31 check codes across the roots found above. Header-only unless `--no-chunk-presence` is off (it is on by default, adding one listing per present level). | ~KB per pyramid |
| `zpa-count-chunks` | For a shortlist of roots: counts chunks actually present per level, `HEAD`s a sample to get stored bytes, and re-encodes a sample locally to measure a real compression ratio. Reports whether stored size is `exact` (all samples full-size) or extrapolated. | HEADs + small GETs |
| `zpa-gate` | Publish-time metadata gate: audits roots you are about to publish and fails closed (exit 1) on any finding at or above `--fail-on` severity (default `high`), on evidence it could not observe, and on roots that do not exist. `--format github` emits `::error`/`::warning` workflow annotations for CI; `--out` writes the versioned JSON report. `--base` may be a local staging directory. Proven live: fails on the header-only PHerc0814 surface volume, passes its populated sibling, fails a nonexistent path ([`2026-10-01-gate-proof`](artifacts/2026-10-01-gate-proof/)). | ~KB per pyramid |
| `zpa-scan-chunks` | Sampled chunk-*content* probe: the audit answers "are chunk keys present?", this answers "do the chunks that are present hold data?". Downloads K sampled chunks per level (first/middle/last of the chunk grid), decodes them, and reports `populated` / `empty` (all fill_value) / `missing` (absent from a shard index) / `undecodable`. Flags levels where every *present* sampled chunk is empty (`CHUNK_SAMPLE_ALL_EMPTY`, medium — genuinely empty background is possible, so this is a review flag, not a verdict). Two-phase fetch for uncompressed chunks: a nonzero byte in the first 4 KiB proves population without downloading the rest. v3 sharded levels (`sharding_indexed`) whose inner codec is **volcomp** — the `dl.ash2txt.org` scroll volumes — are probed by parsing shard indexes over HTTP byte ranges and decoding sampled 128³ inner chunks with a vendored `libvolcomp` (MIT, Linux x86-64; `src/zpa/data/VOLCOMP_PROVENANCE.md`; override with `$VOLCOMP_LIB`). Each shard index's CRC32C is verified before its offsets are trusted: a failing index yields `SHARD_INDEX_CHECKSUM_MISMATCH` (low until validated on a live run — that shard is not sampled, and a non-conforming writer would look the same as corruption); the run summary's `index_crc` tally separates `verified` from `unchecksummed` (index declares no `crc32c`) so a clean run is only read as clean where it says `verified`. Shards with a start-located index are reported `undecodable` rather than misread. Other sharded levels on `s3://` fall back to zarr-python window reads. | KB–MB per pyramid (sampled) |
| `zpa-surface-support` | Measures how much surface-prediction foreground is physically supported by nonzero masked CT on the same voxel grid. Deterministic chunk-aligned slab sampling with an optional exact-volume-ID guard; reports evidence only and does not classify a scroll. | sampled Zarr reads |
| `zpa-surface-depth-profile` | Profiles rendered `[depth,y,x]` surface volumes with deterministic XY tiles. Records per-depth signal/texture, all-zero sampled layers, duplicate sampled-layer digests, peak texture depth, an optional expected-slice-count gate, and an exact source-volume-ID guard. It reports input-window evidence rather than classifying ink. | sampled Zarr reads |
| `zpa-tifxyz` | Audits **tifxyz surface patches** (`meta.json` + float32 `x/y/z.tif`), the Volume Cartographer segment format. Header tier (default): `meta.json` present and well-formed, the three channels present, valid TIFFs (classic or BigTIFF) on one grid, floating-point samples — read with strict range requests, no imaging library. When VC3D metadata provides `source`, `target_volume`, `scroll_source`, `vc_gsfs_mode`, or `vc_gsfs_version`, the report preserves those fields verbatim so downstream prize gates can bind a mesh to its declared target instead of guessing from a filename. Content tier (`--content`): the surface has valid points, channels agree on the `-1` invalid marker, coordinates are finite, and the declared `bbox` matches the stored coordinates. For final-submission preflight, `--expected-target-volume <ID>` is an opt-in fail-closed input guard: every surface must carry VC3D `meta.json.target_volume` identifying that exact CT volume or the run stops before report outputs are written. Tiled/LZW/predictor layouts decode via the optional `[tifxyz]` extra (`tifffile`); without it they are a reported coverage gap. `--fail-on` makes findings a gate. | header: ~KB per surface; content: the three channels |
| `zpa-bench` | Measures what an audit costs per root: wall time, store calls (metadata reads / listings / HEADs / chunk reads) and payload bytes, for the header audit and the sampled chunk probe separately. | the audit's own cost |
| `zpa-dashboard` | Regenerates the [public dashboard](https://svyable.github.io/zarr-pyramid-audit/) (`docs/index.html`) from the committed artifacts; every number on it is read from `artifacts/`, none are hand-typed. | local files only |
| `zpa-known-defects` | Regenerates `data/known-defects.json`, the machine-readable kill list of confirmed defective pyramids. | local files only |

### Check codes

Severities below are the single source of truth in `SEVERITY` (`src/zpa/audit_pyramid.py`).

```
NOT_A_ZARR_GROUP              [info]   no .zgroup/zarr.json and nothing Zarr-like inside
BARE_ARRAY                    [info]   valid single-scale Zarr array; not a pyramid
NOT_MULTISCALE                [info]   valid Zarr group, but not an OME pyramid
CHUNK_EXCEEDS_SHAPE           [info]   chunk larger than the level itself on every axis
ACCESS_UNKNOWN                [info]   attempted access could not establish presence or absence
PHYSICAL_SCALE_UNKNOWN        [info]   metadata explicitly says absolute physical size is unknown
OME_VERSION_UNMODELLED        [info]   declared OME-NGFF version is newer than 0.5 (or unparseable); the TRANSFORM_*/AXES_INVALID checks are skipped
HEADERLESS_CHUNK_STORE        [high]   chunk keys present but no header -- undecodable
METADATA_UNREADABLE           [high]   metadata exists but cannot be decoded
MULTISCALE_EMPTY              [high]   declares multiscales but yields no usable datasets
LEVEL_MISSING                 [high]   declared level has no readable array header
LEVEL_NO_CHUNKS               [high]   valid header, zero chunk keys -- reads return fill_value silently
SCALE_SHAPE_MISMATCH          [high]   shape matches neither ceil nor floor of base/factor
DEGENERATE_LEVEL              [high]   a level has a zero/negative extent
DTYPE_DRIFT                   [high]   dtype changes between levels
SEPARATOR_DRIFT               [high]   dimension_separator changes between levels
NDIM_DRIFT                    [high]   levels disagree on dimensionality
PHYSICAL_SCALE_CONTRADICTION  [high]   physical_size=unknown conflicts with spatial units or a non-identity level-0 spatial scale
LEVEL_UNDECLARED              [medium] numeric level directory exists but is not declared
SCALE_NONMONOTONIC            [medium] declared scales do not strictly increase with depth
MIXED_ROUNDING                [medium] ceil at some levels, floor at others
FILL_DRIFT                    [medium] fill_value changes between levels
COMPRESSOR_DRIFT              [low]    codec changes between levels
AXES_MISMATCH                 [low]    declared axes count != array ndim
TRANSFORM_SCALE_COUNT         [low]    dataset has zero or several scale transforms
TRANSFORM_ARITY               [low]    scale/translation length != axes count (or array ndim)
AXES_INVALID                  [low]    duplicate axis names, or typed axes out of NGFF count/order (2-5 axes, 2-3 space, time<channel<space)
DIMENSION_NAMES_MISMATCH      [low]    OME-Zarr 0.5+: a v3 array's dimension_names are missing or differ from the axes names
CONTAINER_NO_GROUP_HEADER     [low]    children are Zarr nodes but root has no group header
ROOT_ABSENT                   [low]    requested Zarr root is confirmed absent
EMPTY_ZARR_DIR                [low]    *.zarr directory with no contents
```

`OME_VERSION_UNMODELLED`, `TRANSFORM_SCALE_COUNT`, `TRANSFORM_ARITY`,
`AXES_INVALID` and `DIMENSION_NAMES_MISMATCH` are OME-NGFF spec-conformance checks. They are `low`/`info` on
purpose: the 2026-09-29 S3 audit
(`artifacts/2026-09-29-s3/audit_pyramid.{levels,pyramids}.jsonl`) contains no
level without a declared scale, no scale/array length mismatch and no duplicate
axis names, so there is no corpus evidence yet that they mean "do not train". Reproduce with
`python artifacts/log-2026-10-01/corpus_check.py`; the session log
([`artifacts/log-2026-10-01/`](artifacts/log-2026-10-01/)) records the tests,
mutation checks and what is still unverified on live data.
They never fire on untyped axes, an undeclared version, or pre-0.4 metadata,
and an unmodelled version (e.g. OME-Zarr 0.6 / RFC-5 coordinate systems) is
reported rather than judged by 0.4/0.5 rules.

The physical-scale checks are deliberately conservative. They do not guess whether
a voxel size is plausible and they do not infer that an absolute scale is known
merely because the metadata lacks an `unknown` marker. They only expose an
explicitly unknown scale, or fail on metadata that simultaneously says the
physical size is unknown while making an incompatible absolute-scale claim.
This matters for generated scroll renders because an explicitly unknown physical
scale cannot, by itself, support a trustworthy physical-distance scale bar.

### tifxyz surface codes (`zpa-tifxyz`)

| code | severity | fires when |
|---|---|---|
| `TIFXYZ_ABSENT` | low | nothing at the path: no `meta.json`, no channels (integrity `UNKNOWN`, never `PASS`) |
| `TIFXYZ_META_MISSING` | medium | `meta.json` confirmed absent |
| `TIFXYZ_META_UNREADABLE` | medium | `meta.json` present but not a JSON object |
| `TIFXYZ_META_INCOMPLETE` | low | `format` is not `tifxyz`, or `scale` / `bbox` missing or malformed |
| `TIFXYZ_CHANNEL_MISSING` | medium | `x.tif`, `y.tif` or `z.tif` confirmed absent |
| `TIFXYZ_TIFF_UNREADABLE` | medium | a channel is not a parseable TIFF |
| `TIFXYZ_CHANNEL_SHAPE_MISMATCH` | medium | the three channels disagree on the grid |
| `TIFXYZ_SAMPLE_FORMAT` | low | samples are not single floating-point values |
| `TIFXYZ_EMPTY` | medium | *(content)* no valid point at all: the surface has no geometry |
| `TIFXYZ_INVALID_MASK_MISMATCH` | low | *(content)* cells that are `-1` in some channels but not all |
| `TIFXYZ_NONFINITE` | low | *(content)* NaN/inf where the cell is not marked invalid |
| `TIFXYZ_NEGATIVE_COORDINATE` | low | *(content)* valid points with a negative coordinate: outside any CT volume |
| `TIFXYZ_BBOX_MISMATCH` | low | *(content)* declared `bbox` differs from the extent of the stored coordinates |
| `TIFXYZ_CONTENT_UNDECODED` | info | *(content)* layout not decodable here, or over `--max-content-bytes`: a coverage gap |
| `ACCESS_UNKNOWN` | info | a read failed (timeout, 403, 5xx): `UNKNOWN`, never a finding about the data |

None is `high`: promoting one needs corpus-wide evidence (see the 2026-10-01 tifxyz survey below).

## How this fits with ScrolIQ

[ScrolIQ](https://github.com/Svyable/scrollq) is the companion project. (It is spelled with a capital
**I**, as in Mesh IQ and Ink IQ, and was previously called *ScrollQ*; its Python package and the
`scrollq-*` commands keep the old name for compatibility, while its newer diagnostics ship as
`scroliq-*`. Repo and site URLs are unchanged.) The two repos ask one question — *should anyone
spend GPU or expert time on this volume?* — from opposite ends:

| | zarr-pyramid-audit (this repo) | [ScrolIQ](https://github.com/Svyable/scrollq) |
|---|---|---|
| Motto | Don't train on lies | Find the bottleneck |
| Question | Is the data what its metadata says it is? | Which stage of the unwrapping pipeline limits progress, and what is worth doing next? |
| Measures | Pyramid structure, chunk presence and content, publish-time gating, surface-input evidence | Sampled real-voxel scan health (0–100 triage), label/segment coverage (“🎯 label next”), a diagnostic passport, spatial scan maps, mesh / winding / ink audits, 2027 Grand Prize recto-coverage and provenance gates |
| What a result means | **High** severity = do not train, do not publish | Its score is scan-health *triage*, not readability or Grand Prize readiness; unmeasured stages stay `unknown` |
| See | [Dashboard](https://svyable.github.io/zarr-pyramid-audit/) | [Live survey](https://svyable.github.io/scrollq/) · [September writeup](https://svyable.github.io/scrollq/september-2026.html) |

### How they connect

- **One verdict per volume.** ScrolIQ's `scrollq-health` takes integrity from this repo's versioned
  report (`zpa.report.audit_root`) and follows its recommended mapping, so integrity wins and
  missing evidence fails closed: **FAIL** (any high finding, or the audit errored) and **UNKNOWN**
  (an unreadable level, an absent root, nothing to audit) are **DO NOT TRAIN** regardless of score;
  **WARN** (a medium finding) is **CAUTION**; on **PASS**, quality that is unscorable or below 40 is
  **CAUTION**, and anything else is **TRAIN**. Run on live data on 2026-10-01: DO NOT TRAIN on the
  defective PHerc0814 pyramid (FAIL) and on an absent root (UNKNOWN, the negative control), TRAIN
  on a healthy PHerc0813 volume, CAUTION on the v2 dev mesh (integrity PASS, quality unscorable)
  ([ScrolIQ's evidence](https://github.com/Svyable/scrollq/tree/main/artifacts/2026-10-01-health-verdicts-fail-closed)).
  The rules are those of ScrolIQ's
  [`health.py`](https://github.com/Svyable/scrollq/blob/main/src/scrollq/health.py) as checked on
  2026-10-01, after [Svyable/scrollq#55](https://github.com/Svyable/scrollq/pull/55); they live
  there, not here. Before #55 (checked 2026-09-30) ScrolIQ counted severities only, so an
  unreadable level or an absent root could fall through to the quality score
  ([`docs/INTEGRATION.md`](docs/INTEGRATION.md#scroliq-integration-surface)).
- **Shared foundation.** ScrolIQ imports this package's HTTP/S3 store, header parser, audit and the
  vendored `libvolcomp` decoder (`zpa.httpstore`, `zpa.zarrmeta`, `zpa.audit_pyramid`,
  `zpa.volcomp`), and declares `zarr-pyramid-audit` as a dependency. The dependency runs one way:
  this repo never imports ScrolIQ. Treat those four modules' public functions as a contract.
- **Grand Prize evidence chain.** ScrolIQ's `scroliq-provenance` gate requires a `zarr_audit`
  record for the exact eligible CT volume — tool name, the audit manifest's SHA-256, and a
  root that names the volume — and its probe protocol makes running this
  audit on the CT, surface prediction and lasagna inputs Stage A, before any geometry or ink work.
- **Shared discovery data.** ScrolIQ's label-coverage join (`scrollq-coverage`) reads the
  `discover_zarr.roots.jsonl` that `zpa-discover` writes for the S3 bucket.

- **Exact integration surface.** `zpa.httpstore.open_store`, `zpa.zarrmeta.read_pyramid`,
  `zpa.audit_pyramid.audit_one` (finding fields `code`, `severity`, `level`, `detail`), `zpa.volcomp`,
  and, new with contract 1.0.0, `zpa.report.audit_root` / `build_report`, which return a report
  validated by [`src/zpa/data/audit-report.schema.json`](src/zpa/data/audit-report.schema.json)
  (`schema_version` 1.2.0). `tests/test_contract.py` pins the signatures, fields, severities and the
  recommended verdict mapping (`FAIL`/`UNKNOWN` → DO NOT TRAIN, `WARN` → CAUTION). Contract changes
  need a migration note in [`CHANGELOG.md`](CHANGELOG.md). Full guide, including how ScrolIQ's
  `scrollq-health` used to read `ACCESS_UNKNOWN` and `ROOT_ABSENT` as integrity PASS and now
  follows this contract (fail closed, [Svyable/scrollq#55](https://github.com/Svyable/scrollq/pull/55)):
  [`docs/INTEGRATION.md`](docs/INTEGRATION.md#scroliq-integration-surface).

Integrity only, from this repo; or integrity plus scan quality (installing ScrolIQ installs this
package too):

```bash
zpa-gate --base <store> --root <volume.zarr>

pip install git+https://github.com/Svyable/scrollq.git
scrollq-health --root <volume>
```

## Usage

Requires Python 3.11+. Install (also installs the `zpa-*` commands):

```bash
pip install git+https://github.com/Svyable/zarr-pyramid-audit.git
```

Or from a checkout (the `bin/` shims run the same code without installing):

```bash
python -m venv .venv && ./.venv/bin/pip install -e .
```

```bash
zpa-discover --base https://dl.ash2txt.org/ --max-depth 10 --out-dir tmp
```

`--max-depth 10` is not optional for this host: the default (6) stops short of the roots under `community-uploads/bruniss/scrolls/s1/…/old/…` and `Scroll5/…/representations/predictions/fibers/`, which sit 7–8 path segments deep (a depth-6 run finds 229 roots instead of 241).

Zarr **v3** headers (`zarr.json`) are parsed: v3 groups with OME `multiscales`
are audited like v2 pyramids, and a v3 bare array at a root is reported as
`BARE_ARRAY` (info) rather than `NOT_A_ZARR_GROUP`.

```bash
zpa-audit --base https://dl.ash2txt.org/ --roots tmp/discover_zarr.roots.jsonl --max-rps 25 --out-dir tmp
```

```bash
zpa-count-chunks --base https://dl.ash2txt.org/ --from-findings tmp/audit_pyramid.findings.csv \
  --code COMPRESSOR_DRIFT --out-dir tmp
```

Sampled chunk-*content* probe (do present chunks hold data?):

```bash
zpa-scan-chunks --base s3://vesuvius-challenge-open-data/ --levels-jsonl tmp/audit_pyramid.levels.jsonl --out-dir tmp
```

Audit a surface prediction against the exact masked CT volume that produced it:

```bash
zpa-surface-support \
  --predictions s3://vesuvius-challenge-open-data/PHercXXXX/representations/predictions/surfaces/<surface>.zarr \
  --ct s3://vesuvius-challenge-open-data/PHercXXXX/volumes/<exact-prize-volume>.zarr \
  --expected-volume-id <exact-prize-volume-id> \
  --anon --slab-stride 12 --out-dir tmp/surface-support
```

The arrays must share the same voxel grid. The report records exact input paths, threshold, stride, plane coverage, positive/phantom counts, support fraction, and run provenance. For prize work, `--expected-volume-id` fails closed unless that identifier appears in both input paths, reducing the risk of validating a prediction against the wrong same-scroll scan.

Profile the rendered surface-volume stack before ink inference:

```bash
zpa-surface-depth-profile \
  --surface-volume /data/segment/surface-volume.zarr \
  --expected-depth 21 \
  --source-volume-id <exact-prize-volume-id> \
  --expected-volume-id <exact-prize-volume-id> \
  --grid 3 --tile-size 128 --out-dir tmp/surface-depth
```

This catches silent input-window mistakes that ordinary Zarr integrity checks cannot see: an unexpected slice count, sampled all-zero depth planes, or duplicated sampled layers. It also records where gradient energy and dynamic range peak relative to the stack center, which is useful because ink models can be depth-offset sensitive. See [`docs/surface-depth-profile.md`](docs/surface-depth-profile.md).

Audit tifxyz surface patches (header tier; add `--content` to check the coordinates themselves):

```bash
pip install 'zarr-pyramid-audit[tifxyz] @ git+https://github.com/Svyable/zarr-pyramid-audit.git'
zpa-discover --base s3://vesuvius-challenge-open-data/ --max-depth 10 --out-dir tmp/s3
zpa-tifxyz --base s3://vesuvius-challenge-open-data/ --roots tmp/s3/discover_zarr.surfaces.jsonl \
  --content --max-content-bytes 33554432 --out-dir tmp/tifxyz
zpa-tifxyz --base ./staging --root seg.tifxyz --content --fail-on medium   # local preflight
```

`zpa-discover` lists every tifxyz surface it sees in `discover_zarr.surfaces.jsonl` at no extra
request cost (directories ending in `.tifxyz`, and directories holding `x.tif`/`y.tif`/`z.tif`, such
as `mesh/intermediate/tifxyz_original/`). Reports validate against
[`src/zpa/data/tifxyz-report.schema.json`](src/zpa/data/tifxyz-report.schema.json).

Gate a publish (fails closed on high-severity findings, unreadable evidence and absent roots;
exit 0 = clean):

```bash
zpa-gate --base s3://my-bucket/staging/ --roots manifest.jsonl --fail-on high
zpa-gate --base s3://my-bucket/staging/ --root path/to/volume.zarr --format github
zpa-gate --base ./staging --root volume.zarr --out preflight.json   # local tree, before upload
```

Ready-to-copy CI job, preflight script and Python API example: [`examples/`](examples/), explained
in [`docs/INTEGRATION.md`](docs/INTEGRATION.md). ZPA produces the evidence; your workflow owns the
policy.

Outputs land in `--out-dir`: `*.findings.csv` (the reviewable artifact), `*.levels.jsonl`,
`*.pyramids.jsonl`, `*.summary.json`, `*.manifest.json`.

## Continuous verification

Three workflows guard different failure modes:

- `.github/workflows/ci.yml` builds the sdist and wheel on Python 3.11/3.12, installs the built
  wheel, runs the network-free test suite, checks packaged decoder assets, and smoke-tests every
  installed console command.
- `.github/workflows/audit.yml` runs the real-data smoke audit on pushes, pull requests, and every
  Monday: a small anonymous S3 sample, a known-clean gate pass, a known-defective gate rejection,
  and a sampled chunk-content probe.
- `.github/workflows/pages-check.yml` regenerates the dashboard from committed evidence, requires
  `docs/index.html` to match, and verifies local Pages links/assets.

GitHub Pages continues to serve the static `docs/` tree from `main`; `docs/.nojekyll` keeps the
deployment literal and dependency-free. Unit tests can also be run locally with
`python -m pytest tests/ -q`. They include the [fixture corpus](fixtures/README.md): one Zarr
fixture per property (clean, missing level, bad ratios, contradictory or unknown physical scale,
empty / zero-filled / NaN-filled chunks, malformed metadata, HTTP failures, invalid range
responses) with golden structured outputs, replayed both from disk and over a local HTTP server.

`data/known-defects.json` is the machine-readable kill list — every confirmed
defective pyramid across both stores with finding codes, severity, evidence
pointers, and upstream issue links. Regenerate with
`zpa-known-defects` after each audit and diff.

### Auditing the S3 open-data bucket

The same tools run against `s3://vesuvius-challenge-open-data/` (anonymous —
no credentials). The `s3://` scheme selects the `S3Store` backend, which needs
`s3fs` (`pip install -r requirements.txt` includes it):

```bash
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
zpa-discover --base s3://vesuvius-challenge-open-data/ --max-depth 10 --out-dir tmp/s3
zpa-audit --base s3://vesuvius-challenge-open-data/ --roots tmp/s3/discover_zarr.roots.jsonl --workers 16 --out-dir tmp/s3audit
```

`S3Store` also accepts `endpoint_url=` / `region_name=` keyword arguments via
`open_store()` for programmatic use. The regional endpoint matters: the global
`s3.amazonaws.com` endpoint is unreachable from some networks, and without an
explicit endpoint the S3 backend cannot connect at all there.

Full artifacts of the 2026-09-29 S3 run (957 roots discovered, 957 audited,
one confirmed header-only pyramid) are in
[`artifacts/2026-09-29-s3/`](artifacts/2026-09-29-s3/).

## Latest results (2026-09-29 – 2026-10-01)

Every figure below is read from a committed artifact; the
[dashboard](https://svyable.github.io/zarr-pyramid-audit/) is generated from the same files.

**S3 open-data bucket** (`s3://vesuvius-challenge-open-data`, run of 2026-09-29,
[`artifacts/2026-09-29-s3/`](artifacts/2026-09-29-s3/)). 957 roots discovered and audited
header-only: **956 clean, 1 defective** — a PHerc0814 surface volume whose six pyramid levels all
have valid headers and **zero chunks** (6 `LEVEL_NO_CHUNKS`, high). A zarr-python read returns zeros
without error, against a populated control that returned 64,498 nonzero voxels
([`SILENT_ZEROS.md`](artifacts/2026-09-29-s3/SILENT_ZEROS.md)). Re-audited on 2026-09-30 with an
identical result ([`artifacts/2026-09-30-s3-reverify/`](artifacts/2026-09-30-s3-reverify/)); it
independently confirms [villa #1892](https://github.com/scrollprize/villa/issues/1892).

**S3 regression re-audit, 2026-10-01** ([`artifacts/2026-10-01-s3-regression/`](artifacts/2026-10-01-s3-regression/)).
A fresh crawl finds the same 957 roots. Against 2026-09-29: 0 findings fixed, 0 new, 6 unchanged, and all
5,348 levels unchanged, each with direct chunk evidence (none `UNKNOWN`). The PHerc0814 `-L1` pyramid still had
no chunk keys at any level at 07:32 UTC. The matching dl.ash2txt.org re-run is pending: that host was not
reachable from the environment that ran it.

**dl.ash2txt.org 20-day regression**
([`artifacts/2026-09-29-dl-regression/`](artifacts/2026-09-29-dl-regression/)). The 2026-09-09
audit's identical 241-root list, re-run: 18 defective pyramids and 50 actionable findings, and a
strict diff on every finding field is empty — **0 fixed, 0 new**. Published defects do not get
repaired afterwards, which is why the publish-time gate is the point of leverage.

**Chunk-content probes** (2026-09-30; sampled decode — "do the chunks that are present hold
data?"):

| campaign | roots | levels | populated samples | all-empty levels | artifacts |
|---|---|---|---|---|---|
| S3 v2, raw/Blosc | 58 | 291 | 788 | 0 | [`2026-09-30-s3-chunkscan`](artifacts/2026-09-30-s3-chunkscan/) |
| S3 v3, sharded (zarr-python windows) | 70 | 420 | 1,224 | 0 | [`2026-09-30-s3-chunkscan-v3`](artifacts/2026-09-30-s3-chunkscan-v3/) |
| dl volcomp (vendored `libvolcomp`, HTTP byte ranges) | 64 | 384 | 548 | 0 | [`2026-09-30-dl-volcomp-probe`](artifacts/2026-09-30-dl-volcomp-probe/) |
| dl v2, raw/Blosc | 128 | 748 | 1,795 | **7** | [`2026-09-30-dl-v2-probe`](artifacts/2026-09-30-dl-v2-probe/) |

The 7 all-empty levels are `other/dev/meshes/20231022170900-ome.zarr` L1–L7: a dev mesh derivative
(L0 holds data), not a scroll, so it stays **medium** severity for human review. In the volcomp row,
2,118 further samples were *missing* — absent from the shard index, i.e. masked background — and
are deliberately not counted as empty or as defects. "Not observed" in a sample is not proof of
absence in the corpus.

**Publish gate, end to end** ([`artifacts/2026-10-01-gate-proof/`](artifacts/2026-10-01-gate-proof/)).
`zpa-gate --fail-on high`, live against S3, exits 1 on the defective PHerc0814 root, 0 on its
populated sibling `2.399um-0.22m-78keV-volume-20260309142202.zarr`, and 1 on a path that does not
exist. *Correction:* the 2026-09-30 proof's "clean sibling" was such a nonexistent path, which the
gate then passed because `ROOT_ABSENT` is `low` severity. The gate now fails closed on absent roots;
see the erratum in [`2026-09-30-gate-proof`](artifacts/2026-09-30-gate-proof/README.md#erratum-2026-10-01).

**What an audit costs** ([`artifacts/2026-10-01-bench/`](artifacts/2026-10-01-bench/), `zpa-bench`,
six public S3 pyramids, one run each from one cloud container). Confidence costs bytes:

| root (S3) | header audit: time · store calls · payload | findings | sampled chunk probe (3/level): time · reads · payload |
|---|---|---|---|
| PHerc0814 `…-20260521123630-L1.zarr` (defective) | 1.77 s · 16 · 4.6 KiB | 6 × `LEVEL_NO_CHUNKS` | 4.35 s · 0 reads + 41 HEAD · 0 B (no chunks exist) |
| PHerc0814 `2.399um-…-20260309142202.zarr` | 1.50 s · 16 · 4.6 KiB | none | 5.39 s · 20 reads · 5.0 MiB, 17 populated |
| PHerc1447 `8.64um-…-20250521151220.zarr` | 1.75 s · 16 · 3.6 KiB | none | 1.23 s · 13 reads · 877.7 KiB, 13 populated, 1 sparse level not sampled |
| PHerc0009B surface prediction (Blosc/zstd) | 1.52 s · 16 · 5.3 KiB | none | 6.64 s · 12 reads · 2.8 MiB, 12 populated |
| PHerc0343 masked volume (17998 × 8595 × 8595 at L0) | 1.47 s · 16 · 4.4 KiB | none | 6.89 s · 21 reads · 8.1 MiB, 17 populated |
| PHercParis4 ink detection (v3 sharded) | 2.30 s · 22 · 8.9 KiB | none | not measured (sharded path bypasses the counted store API) |

Header audits cost under 9 KiB regardless of array size. The probe costs roughly 240–1,900× more
bytes. Payload bytes exclude HTTP/TLS overhead and S3 listing responses; see the artifact README for
exactly what is and is not counted.

**OME-NGFF conformance re-audit** ([`artifacts/2026-10-01-s3-conformance/`](artifacts/2026-10-01-s3-conformance/)).
All 957 S3 roots re-audited with the spec-conformance checks on: 0 `TRANSFORM_SCALE_COUNT`,
`TRANSFORM_ARITY`, `AXES_INVALID` or `OME_VERSION_UNMODELLED`; every root declares OME-NGFF 0.4; the
2026-09-29 findings are reproduced row for row (956 clean, 1 defective).

**tifxyz surfaces** ([`artifacts/2026-10-01-s3-tifxyz/`](artifacts/2026-10-01-s3-tifxyz/), `zpa-tifxyz`).
All 1,539 tifxyz surface patches in the S3 bucket, found by `zpa-discover`, were audited. All 1,539 are
integrity `PASS`: every one has a readable `meta.json` and three float channels on one grid. The content
tier ran on 1,391 surfaces; 148 have a channel over the 32 MiB cap and are reported as a coverage gap. It
found no empty surface, no channel-mask disagreement and no non-finite coordinate. It did find:
- **161 surfaces with points outside any CT volume** (`TIFXYZ_NEGATIVE_COORDINATE`), mostly final
  registered surfaces (143 of 709), mostly on z, median 4.5% of a surface's points and up to 39.7%. In
  a worked PHerc0139 example the surface runs past both ends of its target volume's z range, so a render
  from that volume has no CT data there. Every one of these surfaces' `meta.json` bbox already shows the
  negative extent.
- **30 surfaces whose `meta.json` bbox disagrees with the stored coordinates**
  (`TIFXYZ_BBOX_MISMATCH`):
  - 28 have the `-1` invalid marker leaked into the declared minimum (one PHercParis4 batch of
    `tifxyz_original` intermediates);
  - 2 store points outside the declared box, 2,375 and 755 points, so cropping to the bbox would drop
    geometry.

All are `low` review findings.

**Against existing tools** ([`artifacts/2026-10-01-baseline-comparison/`](artifacts/2026-10-01-baseline-comparison/),
zarr-python 3.1.6 and the ome-zarr-models 1.7 OME-NGFF validator). On the live PHerc0814 defect both
baselines treat the pyramid as healthy: the validator accepts it, and zarr-python reads a level-5
window as 249,856 voxels, all zero, without an error. The gate rejects it. On the fixture corpus,
defects flagged: zarr-python 8 / 26, the validator 14 / 26, the ZPA header audit 25 / 26, and with
the sampled chunk probe 26 / 26. The corpus was written around ZPA's failure classes, so read it per
defect class rather than as a score. The validator checks the full NGFF spec, which ZPA does not;
the two are complementary. ZPA's false alarms on valid pyramids (1 / 10 header-only, 2 / 10 with the
probe) and the caveats are in the artifact README. A third baseline, the yaozarrs 0.3.2 validator,
which also checks that each declared level exists as an array of the right dimensionality, was added
on 2026-10-03 ([`artifacts/2026-10-03-baseline-yaozarrs/`](artifacts/2026-10-03-baseline-yaozarrs/)):
it accepts the live defect too, and flags 13 / 26 fixture defects.

**Known defects.** [`data/known-defects.json`](data/known-defects.json) lists 19 confirmed
defective pyramids across both stores, with finding codes, severity and evidence pointers.

## Original baseline: dl.ash2txt.org (run of 2026-09-09)

Full artifacts in [`artifacts/2026-09-09/`](artifacts/2026-09-09/).

Discovery crawled 19,995 directory listings with 0 errors and found **241 Zarr roots**. All 241 were
audited in 141 seconds.

| | |
|---|---|
| pyramids audited | 241 |
| clean (no finding of any kind) | 111 |
| with **actionable** defects | **18** |
| findings: high / low / info | 40 / 10 / 125 |

| code | count | severity | roots |
|---|---|---|---|
| `CHUNK_EXCEEDS_SHAPE` | 78 | info (triaged benign) | — |
| `BARE_ARRAY` | 40 | info | — |
| `SCALE_SHAPE_MISMATCH` | 15 | high | 3 |
| `LEVEL_MISSING` | 13 | high | 3 |
| `LEVEL_NO_CHUNKS` | 11 | high | 2 |
| `COMPRESSOR_DRIFT` | 9 | low | 9 |
| `NOT_MULTISCALE` | 6 | info | — |
| `HEADERLESS_CHUNK_STORE` | 1 | high | 1 |
| `CONTAINER_NO_GROUP_HEADER` | 1 | low | 1 |
| `NOT_A_ZARR_GROUP` | 1 | info | — |

**Cross-validation.** 64 of the 241 roots mirror the 64 volumes on `s3://vesuvius-challenge-open-data`,
which already has an independent auditor
([Bullo27/scroll-data-audit](https://github.com/Bullo27/scroll-data-audit)). This tool reports
**0 defects** on all 64 — the same verdict, reached with a different codebase and a different
transport. Every defect found is in the 177 roots that tool does not cover.

**Also clean across all 241:** no dtype drift, ndim drift, fill-value drift, `dimension_separator`
drift, non-monotonic scales, mixed ceil/floor rounding, or undeclared level directories.

### The sharpest single finding

`other/dev/inked_zarrs/3336_predictions.zarr` declares a 6-level pyramid, has a valid `.zarray` at
**all six** levels, and contains **zero chunk files at every one of them**. `fill_value` is `0`, so
`zarr.open()` succeeds and every read returns zeros — with no error, at any level, ever.

```bash
B=https://dl.ash2txt.org/other/dev/inked_zarrs/3336_predictions.zarr
for l in 0 1 2 3 4 5; do printf "L$l .zarray="; curl -s -o /dev/null -w "%{http_code}" $B/$l/.zarray; printf "  chunks="; curl -s $B/$l/ | grep -c 'href="[^.]'; done
```

## Limitations

- **Metadata consistency is not volumetric semantic correctness.** A pyramid can pass every check
  and still hold the wrong scan, a misregistered render, or a bad segmentation. ZPA checks structure,
  presence and self-consistency, not meaning.
- **A sampled chunk probe is evidence, not exhaustive validation.** `zpa-scan-chunks` decodes a few
  chunks per level (3 by default). It can miss a populated chunk among empty ones (fixture
  `partially_empty`) or find no stored chunk at its sample positions on a sparse level
  (`CHUNK_LEVEL_NO_SAMPLES`, a coverage gap). `CHUNK_SAMPLE_ALL_EMPTY` is a `medium` review flag,
  because genuinely empty background exists.
- **Network and access failures stay unknown.** A timeout, 401/403, 429, 5xx or unreadable listing is
  recorded as `UNKNOWN`. It never becomes "missing" or "empty", and the report's `integrity` is then
  `UNKNOWN`, never `PASS`. The gate fails closed on it unless you pass `--ignore-unreadable`.
- **Chunk presence needs a trustworthy listing.** Without an autoindex that shows the level header,
  `LEVEL_NO_CHUNKS` cannot be proven and the level's chunk evidence stays `UNKNOWN`. That is
  reported under `coverage`, not as a finding.
- **Missing ≠ empty ≠ zero-filled.** A chunk absent from a listing or shard index is masked
  background. A stored chunk equal to `fill_value` is "empty". Stored zeros with a non-zero fill
  are data. The fixture corpus pins all three.
- **Severities are policy-laden.** `high` means "do not train / do not publish" for the failure class
  this project targets. Your pipeline may need a stricter threshold (`--fail-on medium`).
- **Coverage of codecs and hosts.** The chunk probe decodes raw, Blosc and volcomp-sharded chunks
  (Linux x86-64 for the vendored decoder). Other codecs are reported `CHUNK_UNDECODEABLE`, never
  guessed.
- **Surfaces: tifxyz only, and content up to a cap.** `zpa-tifxyz` audits tifxyz quadmeshes; it
  reads full channels only with `--content`, and only up to `--max-content-bytes` per channel (256 MiB by
  default; the 2026-10-01 survey used 32 MiB). Larger surfaces get `TIFXYZ_CONTENT_UNDECODED`, a coverage gap, not a pass. Triangular
  meshes (`.obj`, `.ply`) are not audited here; mesh and winding audits live in ScrolIQ.

## Accuracy policy

Every actionable finding was re-verified with `curl` against the live server, independent of the
tool, before being reported. Storage figures from `count_chunks.py` distinguish **measured** from
**modelled**: each level records whether its stored-bytes figure is `exact` (every sampled chunk was
full size) or extrapolated, and compression ratios derived from small samples are reported as
order-of-magnitude with their sample size, not to spurious precision.

## Contributing

See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). Dev setup is `pip install -e '.[dev]'`
then `python -m pytest tests/ -q`. AI coding agents: [`AGENTS.md`](AGENTS.md).

## Data attribution and license

Every finding in this repository was derived from metadata (`.zattrs`, `.zarray`, `.zgroup`, and
directory listings) served publicly by the Vesuvius Challenge at `dl.ash2txt.org`. No dataset files
are redistributed here; the committed artifacts are the auditor's own derived JSON/CSV output.

The underlying data is released under [CC-BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
unless otherwise noted for specific assets, and comes from two datasets that must be cited separately
(see [scrollprize.org/data](https://scrollprize.org/data)):

- **Vesuvius Challenge - CT Scans of Herculaneum Papyri** (newer scans released directly by
  Vesuvius Challenge, including Scroll 5 and the `other/` community uploads audited here):

  > Giorgio Angelotti, Stephen Parsons, Sean Johnson, Elian Rafael Dal Prà, Johannes Rudolph,
  > Paul Tafforeau, Alessandro Mirone, Paul Henderson, Hendrik Schilling, Forrest McDonald,
  > David Josey, Youssef Nader, C. Seth Parker, W. Brent Seales. *Vesuvius Challenge - CT Scans of
  > Herculaneum Papyri*. Vesuvius Challenge.

- **EduceLab-Scrolls** (Scrolls 1-4 and Fragments 1-6 scanned at DLS before 2025 — this covers the
  Frag3 finding). Copyright EduceLab / The University of Kentucky:

  > Parsons, S., Parker, C. S., Chapman, C., Hayashida, M., & Seales, W. B. (2023).
  > *EduceLab-Scrolls: Verifiable Recovery of Text from Herculaneum Papyri using X-ray CT*.
  > arXiv [cs.CV]. https://doi.org/10.48550/arXiv.2304.02084

  Data used in the preparation of this work were obtained from the EduceLab-Scrolls dataset.

The auditor code itself is MIT-licensed (see `LICENSE`); that license covers the tooling only, not
the data it was run against.

## Disclosure

Investigation and tooling were carried out with Claude (Anthropic) under the direction of James Ryan,
who reviewed each step and approved every run against the public server. All access was read-only and
rate-limited.
