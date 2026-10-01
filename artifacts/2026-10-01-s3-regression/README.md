# S3 regression re-audit — 2026-10-01 (October goal G1, S3 half)

G1 in [`docs/october-2026.html`](../../docs/october-2026.html) asks for a dated
re-verification of the live state on both hosts. This is the S3 half: a
fresh crawl of the bucket, a header-only audit of every root it finds, and a
strict diff against the first S3 run
([`../2026-09-29-s3/`](../2026-09-29-s3/)).

**The dl.ash2txt.org half is not done.** The network policy of the
environment that produced this run refused `dl.ash2txt.org` (proxy CONNECT
403), as it did for every 2026-10-01 run. It needs an environment that can
reach that host; see "dl.ash2txt.org" below.

## Commands

Code: `main` at `ff1ecaa` (the audit is unchanged by this branch, which only
adds the scripts in this directory). Started 2026-10-01 07:25 UTC.

```bash
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
zpa-discover --base s3://vesuvius-challenge-open-data/ --max-depth 10 --out-dir tmp/g1/discover
zpa-audit --base s3://vesuvius-challenge-open-data/ \
  --roots tmp/g1/discover/discover_zarr.roots.jsonl --workers 16 --out-dir tmp/g1/audit

python artifacts/2026-10-01-s3-regression/regression_diff.py \
  --baseline artifacts/2026-09-29-s3 --current artifacts/2026-10-01-s3-regression \
  --json artifacts/2026-10-01-s3-regression/regression_diff.json
python artifacts/2026-10-01-s3-regression/compare_levels.py \
  artifacts/2026-09-29-s3/audit_pyramid.levels.jsonl tmp/g1/audit/audit_pyramid.levels.jsonl
```

Discovery: 07:25–07:29 UTC, 7,490 directory listings, 0 listing errors.
Audit: 07:29–07:32 UTC.

## Result

| | 2026-09-29 | 2026-10-01 |
|---|---|---|
| directory listings (errors) | 7,487 (0) | 7,490 (0) |
| Zarr roots discovered | 957 | 957, the identical set |
| tifxyz surfaces discovered | (not recorded) | 1,539, identical to [`../2026-10-01-s3-tifxyz/`](../2026-10-01-s3-tifxyz/) |
| roots audited | 957 | 957 |
| clean / with defects | 956 / 1 | 956 / 1 |
| findings | 6 × `LEVEL_NO_CHUNKS` (high) | 6 × `LEVEL_NO_CHUNKS` (high) |

**Findings diff** (`regression_diff.txt`, `regression_diff.json`), keyed on
every field of the findings CSV: **0 fixed, 0 new, 6 unchanged**; no root
added or dropped.

**Level diff** (`compare_levels.txt`): all 5,348 levels match on presence,
shape, chunks, dtype, fill value, compressor, separator, chunk presence and
top-level entry count. `zarr_format` is not compared because the 2026-09-29
tool version did not record it.

**Evidence coverage.** Every one of the 5,348 levels has a readable header
(`evidence_state` `PRESENT`) and direct chunk evidence: 5,342 `PRESENT`, and
6 `ABSENT` with reason `NO_CHUNK_KEYS`. No level's chunk evidence is
`UNKNOWN`, so the clean verdicts above do not rest on unreadable data.

**Live state at 2026-10-01 07:32 UTC.** The PHerc0814 surface volume
`1.129um-0.22m-59keV-volume-20260521123630-L1.zarr` still has headers at all
six levels and no chunk keys at any of them, unchanged since the 2026-09-29
run and the 2026-09-30 re-verification
([`../2026-09-30-s3-reverify/`](../2026-09-30-s3-reverify/)). It is
independently reported as [villa #1892](https://github.com/scrollprize/villa/issues/1892).

## What this does and does not show

- The bucket's Zarr pyramids did not change between the two runs as far as
  headers and listings can show: no root added, removed or altered. It says
  nothing about chunk *contents*; the sampled probes for that are
  [`../2026-09-30-s3-chunkscan/`](../2026-09-30-s3-chunkscan/) and
  [`../2026-09-30-s3-chunkscan-v3/`](../2026-09-30-s3-chunkscan-v3/).
- Two days is a short window. The point of the run is that the published S3
  numbers are re-verified on a date, not a claim about how fast the bucket
  changes.

## dl.ash2txt.org

Still to do for G1, from an environment that can reach the host:

```bash
zpa-audit --base https://dl.ash2txt.org/ \
  --roots artifacts/2026-09-09/discover_zarr.roots.jsonl --out-dir tmp/g1/dl
# copy the CSV, summary, pyramids.jsonl and manifests into artifacts/<date>-dl-regression/
python artifacts/2026-10-01-s3-regression/regression_diff.py \
  --baseline artifacts/2026-09-09 --current artifacts/<date>-dl-regression
```

The same script reproduces the published 2026-09-29 dl result from the
committed files (`--baseline artifacts/2026-09-09 --current
artifacts/2026-09-29-dl-regression`: 0 fixed, 0 new, 175 unchanged, 18
defective roots).

## Files

- `discover_zarr.roots.jsonl`, `discover_zarr.manifest.json`: the crawl
  (the 1.3 MB `dirs.jsonl` and the surfaces list are not committed; the
  surfaces match `../2026-10-01-s3-tifxyz/discover_zarr.surfaces.jsonl`).
- `audit_pyramid.findings.csv`, `.summary.json`, `.pyramids.jsonl`,
  `.manifest.json`: the audit. The 3.2 MB `levels.jsonl` is not committed;
  re-run the audit to regenerate it.
- `regression_diff.py` / `.txt` / `.json`, `compare_levels.py` / `.txt`:
  the diffs above.
