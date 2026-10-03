# dl.ash2txt.org defect regression check — 2026-10-03

Thirty-four days after the 2026-09-09 audit published 18 structurally
defective pyramids (villa #1755–#1760), and four days after the 2026-09-29
regression: **were any of them fixed?**

## Method

Re-ran `zpa-audit` over the exact 241-root list from the 2026-09-09
discovery (`artifacts/2026-09-09/discover_zarr.roots.jsonl`), header-only.

```bash
.venv/bin/zpa-audit --base https://dl.ash2txt.org/ \
  --roots artifacts/2026-09-09/discover_zarr.roots.jsonl \
  --workers 6 --out-dir artifacts/2026-10-03-dl-regression
```

## Result

| | 2026-09-09 | 2026-09-29 | 2026-10-03 |
|---|---|---|---|
| pyramids audited | 241 | 241 | 241 |
| pyramids with defects | 18 | 18 | 18 |
| actionable findings | 50 | 50 | 50 |
| total findings | 175 | 175 | 175 |

A strict diff on (root, level, code, detail) is **empty**:
zero fixed, zero new, 175 unchanged.

## What this means

Thirty-four days after publication with per-finding reproduction evidence,
every defective pyramid is defective in exactly the same way — missing
levels, header-only levels, scale/shape mismatches, compressor drift, the
headerless chunk store. Published data defects do not get fixed after the
fact. This is the third consecutive clean regression confirming it.
