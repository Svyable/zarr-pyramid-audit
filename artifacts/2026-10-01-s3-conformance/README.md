# S3 re-audit with OME-NGFF conformance checks — 2026-10-01

Live check of #16's premise that the new conformance codes add no noise on
real data. Header-only audit of the same 957 roots as the 2026-09-29 run,
with the code at `c86652e` (#16 merged with `main`; the four conformance
codes are active):

```bash
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
zpa-audit --base s3://vesuvius-challenge-open-data/ \
  --roots artifacts/2026-09-29-s3/discover_zarr.roots.jsonl \
  --workers 16 --out-dir artifacts/2026-10-01-s3-conformance
```

Committed: `audit_pyramid.summary.json`, `audit_pyramid.findings.csv`,
`audit_pyramid.pyramids.jsonl` (carries each pyramid's `ome_version`),
`audit_pyramid.manifest.json`. The 3.2 MB `levels.jsonl` is not committed;
re-run the command to regenerate it.

## Result

| | 2026-09-29 baseline | 2026-10-01, conformance checks on |
|---|---|---|
| roots audited | 957 | 957 |
| clean / with defects | 956 / 1 | 956 / 1 |
| findings | 6 × `LEVEL_NO_CHUNKS` (high) | 6 × `LEVEL_NO_CHUNKS` (high) |
| `TRANSFORM_SCALE_COUNT` / `TRANSFORM_ARITY` / `AXES_INVALID` | (not implemented) | **0 / 0 / 0** |
| `OME_VERSION_UNMODELLED` | (not implemented) | **0** |
| declared OME-NGFF version | (not recorded) | `0.4` on all 957 |

The findings are identical row for row on (code, severity, root, level) to
`../2026-09-29-s3/audit_pyramid.findings.csv`: the only defect is still the
PHerc0814 `-L1` surface volume.

## What this does and does not show

- On this bucket the conformance checks are **silent**, as #16 predicted from
  level records. This run confirms it from the actual multiscales metadata,
  so the codes stay `low`: there is still no corpus evidence that they mean
  "do not train".
- Every root declares 0.4, so the version gate never skipped a pyramid here.
- Not covered: `dl.ash2txt.org` (unreachable from the environment that ran
  this), and the volcomp shard-index CRC32C check (`zpa-scan-chunks` on
  volcomp shards, which live only on `dl.ash2txt.org`).
