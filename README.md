# zarr-pyramid-audit

Read-only integrity auditing for OME-Zarr multiscale pyramids served over HTTP or S3.

**[Live data-health dashboard](https://svyable.github.io/zarr-pyramid-audit/)** — the public,
visual summary generated from the committed audit artifacts. The deployable source lives in
[`docs/`](docs/); pull requests verify that the generated dashboard is current before merge.

Built to audit [`dl.ash2txt.org`](https://dl.ash2txt.org/) (the Vesuvius Challenge / Scroll Prize
data host), but nothing in it is Vesuvius-specific: point `--base` at any store that exposes a
directory autoindex and it works.

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

**It does not depend on `zarr`.** Headers are parsed directly from `.zattrs` / `.zarray` /
`zarr.json`. This is deliberate: a store that `zarr.open()` refuses to open is exactly the kind of
defect the tool needs to *report*, not crash on.

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
| `zpa-audit` | 26 check codes across the roots found above. Header-only unless `--no-chunk-presence` is off (it is on by default, adding one listing per present level). | ~KB per pyramid |
| `zpa-count-chunks` | For a shortlist of roots: counts chunks actually present per level, `HEAD`s a sample to get stored bytes, and re-encodes a sample locally to measure a real compression ratio. Reports whether stored size is `exact` (all samples full-size) or extrapolated. | HEADs + small GETs |
| `zpa-gate` | Publish-time metadata gate: audits roots you are about to publish and fails closed (exit 1) on any finding at or above `--fail-on` severity (default `high`). `--format github` emits `::error`/`::warning` workflow annotations for CI. Tested: fails on the header-only PHerc0814 surface volume, passes on clean volumes. | ~KB per pyramid |
| `zpa-scan-chunks` | Sampled chunk-*content* probe: the audit answers "are chunk keys present?", this answers "do the chunks that are present hold data?". Downloads K sampled chunks per level (first/middle/last of the chunk grid), decodes them, and reports `populated` / `empty` (all fill_value) / `missing` (absent from a shard index) / `undecodable`. Flags levels where every *present* sampled chunk is empty (`CHUNK_SAMPLE_ALL_EMPTY`, medium — genuinely empty background is possible, so this is a review flag, not a verdict). Two-phase fetch for uncompressed chunks: a nonzero byte in the first 4 KiB proves population without downloading the rest. v3 sharded levels (`sharding_indexed`) whose inner codec is **volcomp** — the `dl.ash2txt.org` scroll volumes — are probed by parsing shard indexes over HTTP byte ranges and decoding sampled 128³ inner chunks with a vendored `libvolcomp` (MIT, Linux x86-64; `src/zpa/data/VOLCOMP_PROVENANCE.md`; override with `$VOLCOMP_LIB`). Other sharded levels on `s3://` fall back to zarr-python window reads. | KB–MB per pyramid (sampled) |
| `zpa-surface-support` | Measures how much surface-prediction foreground is physically supported by nonzero masked CT on the same voxel grid. Deterministic chunk-aligned slab sampling with an optional exact-volume-ID guard; reports evidence only and does not classify a scroll. | sampled Zarr reads |
| `zpa-surface-depth-profile` | Profiles rendered `[depth,y,x]` surface volumes with deterministic XY tiles. Records per-depth signal/texture, all-zero sampled layers, duplicate sampled-layer digests, peak texture depth, an optional expected-slice-count gate, and an exact source-volume-ID guard. It reports input-window evidence rather than classifying ink. | sampled Zarr reads |

### Check codes

```
NOT_A_ZARR_GROUP          [info] no .zgroup/zarr.json and nothing Zarr-like inside
BARE_ARRAY                [info] valid single-scale Zarr array; not a pyramid
NOT_MULTISCALE            [info] valid Zarr group, but not an OME pyramid
CHUNK_EXCEEDS_SHAPE       [info] chunk larger than the level itself on every axis
HEADERLESS_CHUNK_STORE    chunk keys present but no header -- undecodable
CONTAINER_NO_GROUP_HEADER children are Zarr nodes but root has no group header
ROOT_ABSENT              requested Zarr root is confirmed absent
ACCESS_UNKNOWN           [info] attempted access could not establish presence or absence
METADATA_UNREADABLE      metadata exists but cannot be decoded
EMPTY_ZARR_DIR            *.zarr directory with no contents
MULTISCALE_EMPTY          declares multiscales but yields no usable datasets
LEVEL_MISSING             declared level has no readable array header
LEVEL_NO_CHUNKS           valid header, zero chunk keys -- reads return fill_value silently
LEVEL_UNDECLARED          numeric level directory exists but is not declared
SCALE_NONMONOTONIC        declared scales do not strictly increase with depth
SCALE_SHAPE_MISMATCH      shape matches neither ceil nor floor of base/factor
MIXED_ROUNDING            ceil at some levels, floor at others
DTYPE_DRIFT / FILL_DRIFT / COMPRESSOR_DRIFT / SEPARATOR_DRIFT / NDIM_DRIFT
AXES_MISMATCH             declared axes count != array ndim
DEGENERATE_LEVEL          a level has a zero/negative extent
PHYSICAL_SCALE_UNKNOWN    [info] metadata explicitly says absolute physical size is unknown
PHYSICAL_SCALE_CONTRADICTION
                           physical_size=unknown conflicts with spatial units or
                           a non-identity level-0 spatial scale
```

The physical-scale checks are deliberately conservative. They do not guess whether
a voxel size is plausible and they do not infer that an absolute scale is known
merely because the metadata lacks an `unknown` marker. They only expose an
explicitly unknown scale, or fail on metadata that simultaneously says the
physical size is unknown while making an incompatible absolute-scale claim.
This matters for generated scroll renders because an explicitly unknown physical
scale cannot, by itself, support a trustworthy physical-distance scale bar.

## Usage

Install (also installs the `zpa-*` commands):

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
zpa-count-chunks --base https://dl.ash2txt.org/ --roots-csv shortlist.csv --out-dir tmp
```

Sampled chunk-*content* probe (do present chunks hold data?):

```bash
zpa-scan-chunks --base s3://vesuvius-challenge-open-data/ --levels-jsonl tmp/audit_pyramid.levels.jsonl --out-dir tmp
```

Audit a surface prediction against the exact masked CT volume that produced it:

```bash
zpa-surface-support \\
  --predictions s3://vesuvius-challenge-open-data/PHercXXXX/representations/predictions/surfaces/<surface>.zarr \\
  --ct s3://vesuvius-challenge-open-data/PHercXXXX/volumes/<exact-prize-volume>.zarr \\
  --expected-volume-id <exact-prize-volume-id> \\
  --anon --slab-stride 12 --out-dir tmp/surface-support
```

The arrays must share the same voxel grid. The report records exact input paths, threshold, stride, plane coverage, positive/phantom counts, support fraction, and run provenance. For prize work, `--expected-volume-id` fails closed unless that identifier appears in both input paths, reducing the risk of validating a prediction against the wrong same-scroll scan.

Profile the rendered surface-volume stack before ink inference:

```bash
zpa-surface-depth-profile \\
  --surface-volume /data/segment/surface-volume.zarr \\
  --expected-depth 21 \\
  --source-volume-id <exact-prize-volume-id> \\
  --expected-volume-id <exact-prize-volume-id> \\
  --grid 3 --tile-size 128 --out-dir tmp/surface-depth
```

This catches silent input-window mistakes that ordinary Zarr integrity checks cannot see: an unexpected slice count, sampled all-zero depth planes, or duplicated sampled layers. It also records where gradient energy and dynamic range peak relative to the stack center, which is useful because ink models can be depth-offset sensitive. See [`docs/surface-depth-profile.md`](docs/surface-depth-profile.md).

Gate a publish (fails closed on high-severity findings; exit 0 = clean):

```bash
zpa-gate --base s3://my-bucket/staging/ --roots manifest.jsonl --fail-on high
zpa-gate --base s3://my-bucket/staging/ --root path/to/volume.zarr --format github
```

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
`python -m pytest tests/ -q`.

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

## Results on dl.ash2txt.org (run of 2026-09-09)

## Companion project

[ScrollQ](https://github.com/Svyable/scrollq) scores every scroll volume
0–100 on data quality — signal presence, texture energy, dynamic range,
dead-slice scan — and joins the ranking against published ink labels to flag
"🎯 label next" targets ([live leaderboard](https://svyable.github.io/scrollq/)).
This repo is "don't train on lies" (corruption); ScrollQ is "train on the
best first" (triage). `scrollq-health` (in the ScrollQ package) runs both
halves and issues one verdict per volume: **TRAIN / CAUTION / DO NOT TRAIN**.

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

## Accuracy policy

Every actionable finding was re-verified with `curl` against the live server, independent of the
tool, before being reported. Storage figures from `count_chunks.py` distinguish **measured** from
**modelled**: each level records whether its stored-bytes figure is `exact` (every sampled chunk was
full size) or extrapolated, and compression ratios derived from small samples are reported as
order-of-magnitude with their sample size, not to spurious precision.

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
