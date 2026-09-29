# dl.ash2txt.org defect regression check — 2026-09-29

Twenty days after the 2026-09-09 audit published 18 structurally defective
pyramids (villa #1755–#1760) with per-finding reproduction evidence: **were
any of them fixed?**

## Method

Re-ran `bin/audit_pyramid.py` over the exact 241-root list from the 2026-09-09
discovery (`artifacts/2026-09-09/discover_zarr.roots.jsonl`), header-only,
with the current tool (including the v3 bare-array classification fix — which
does not affect this corpus, whose roots predate the v3 discovery).

## Result

| | 2026-09-09 | 2026-09-29 |
|---|---|---|
| pyramids audited | 241 | 241 |
| pyramids with defects | 18 | 18 |
| actionable findings | 50 | 50 |
| total findings | 175 | 175 |

A strict diff on (root, level, code, detail, observed, expected) is **empty**:
zero findings fixed, zero new findings. Every defective pyramid is defective
in exactly the same way it was 20 days ago — missing levels, header-only
levels, scale/shape mismatches, compressor drift, the headerless chunk store.

## What this means

Published data defects do not get fixed after the fact, even with precise
reproduction evidence attached. The defects have to be caught *before*
publication — which is what `bin/gate.py` (added in this fork) is for: a
publish-time metadata gate that fails closed on any structural defect at or
above a chosen severity, with GitHub Actions annotation output for CI.

## Files

Same layout as the 2026-09-09 artifacts: `audit_pyramid.findings.csv` (the
reviewable artifact), `*.levels.jsonl`, `*.pyramids.jsonl`, `*.summary.json`,
`*.manifest.json` (provenance: argv, host, package versions).
