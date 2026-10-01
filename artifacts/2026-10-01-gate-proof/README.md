# zpa-gate end-to-end proof — 2026-10-01

Supersedes [`2026-09-30-gate-proof`](../2026-09-30-gate-proof/) (see the erratum
there). Run live against `s3://vesuvius-challenge-open-data` with
`AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com`; each `.log` starts
with the exact command and ends with the exit code, and each `.json` is the
`--out` report (`schema_version` 1.0.0, one schema-valid audit report per root).

| case | root (under `PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/`) | verdict | exit |
|---|---|---|---|
| defective | `1.129um-0.22m-59keV-volume-20260521123630-L1.zarr` | FAIL — 6 × `LEVEL_NO_CHUNKS` (high), integrity `FAIL` | 1 |
| clean sibling | `2.399um-0.22m-78keV-volume-20260309142202.zarr` | PASS — no findings, integrity `PASS` | 0 |
| absent path | `1.129um-0.22m-59keV-volume-20260521123630.zarr` | ABSENT — `GATE_ROOT_ABSENT` (root confirmed absent), integrity `UNKNOWN` | 1 |

The clean sibling is one of the two populated renders of the same segment
named in [`2026-09-29-s3/SILENT_ZEROS.md`](../2026-09-29-s3/SILENT_ZEROS.md);
the 2026-09-29 audit reported no findings for it, and the 2026-10-01 benchmark
([`2026-10-01-bench`](../2026-10-01-bench/)) decoded populated chunks from it.

The third row is the regression this run exists to pin: before 2026-10-01 the
gate *passed* a root that does not exist (`ROOT_ABSENT` is `low`, below the
default `high` threshold), so a typo in a publish manifest read as success.
It now fails closed; `--allow-absent` restores the old behaviour explicitly.

```bash
P=PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes
zpa-gate --base s3://vesuvius-challenge-open-data --root "$P/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr" --out gate-rejects-defective.json   # exit 1
zpa-gate --base s3://vesuvius-challenge-open-data --root "$P/2.399um-0.22m-78keV-volume-20260309142202.zarr" --out gate-passes-clean.json          # exit 0
zpa-gate --base s3://vesuvius-challenge-open-data --root "$P/1.129um-0.22m-59keV-volume-20260521123630.zarr" --out gate-rejects-absent.json        # exit 1
```
