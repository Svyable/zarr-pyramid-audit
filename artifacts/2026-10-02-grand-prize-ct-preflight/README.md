# Exact-volume Grand Prize CT preflight — 2026-10-02

This artifact intersects the frozen **2026-09-29 public S3 pyramid audit** with
the **13 exact CT volumes eligible for the 2027 Grand Prize**.

The prize manifest is copied here from
`Svyable/scrollq/artifacts/2026-10-01-prize-targets/grand-prize-manifest.json`.
That manifest was itself derived from pinned official eligibility and bucket
metadata. Keeping a copy here makes this cross-cut fully offline-reproducible.

## Result

**13 / 13 exact prize-listed CT roots were found** in the frozen S3 audit.

For all 13:

- all **6 / 6** declared pyramid levels were present;
- no level was reported with zero chunk objects;
- no level had unknown chunk-presence evidence;
- the audit recorded no read/metadata errors;
- the header audit recorded **0 findings**.

This is the useful conclusion: none of the 13 prize CT inputs exhibits the
silent structural failure classes that ZPA found elsewhere in the public
bucket as of the 2026-09-29 campaign.

It is also deliberately narrow. This does **not** establish scan quality,
semantic voxel correctness, surface identity, recto coverage, flattening
quality, or ink.

## Reproduce

From the repository root:

```bash
python artifacts/2026-10-02-grand-prize-ct-preflight/derive.py
git diff --exit-code artifacts/2026-10-02-grand-prize-ct-preflight/summary.json
```

Inputs:

- `artifacts/2026-10-02-grand-prize-ct-preflight/prize-manifest.json`
- `artifacts/2026-09-29-s3/audit_pyramid.pyramids.jsonl`

The matching rule is exact `scroll + volume_id`; same-scroll substitute scans
do not count.

## Why this matters

The Grand Prize fixes each target to a specific eligible CT scan. A generic
"this scroll was audited" statement is therefore insufficient. This artifact
pins the integrity statement to the exact prize-listed volume IDs and makes the
current preflight state inspectable target by target.

Before any final submission freeze, this dated 2026-09-29 state should be
re-audited against the live store.

## Claim boundary

A ZPA header PASS is an input-integrity preflight, not a readiness verdict.
The Grand Prize still requires complete surface reconstruction, VC3D
integration, flattening, legible ink, false-positive mitigation, held-out
validation, and submission packaging.
