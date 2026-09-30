# AGENTS.md — zarr-pyramid-audit

Instructions for AI coding agents working in this repo. Humans: the
contributing guide lives at `.github/CONTRIBUTING.md`.

## What this is

Corruption detection for OME-Zarr multiscale pyramids in the Vesuvius open
data: header-only audits, a publish-time gate, and a sampled chunk-*content*
probe. "Don't train on lies." Companion: [ScrollQ](https://github.com/Svyable/scrollq)
("train on the best first" — quality scoring).

**This is a fork** of [sgsllc-jr/zarr-pyramid-audit](https://github.com/sgsllc-jr/zarr-pyramid-audit)
(MIT). Upstream credit is retained in the README and LICENSE.

## Remotes — read this first

- `fork` → `Svyable/zarr-pyramid-audit` — **ours. Push here.**
- `origin` → `sgsllc-jr/zarr-pyramid-audit` — upstream, read-only.
- Branch `main` tracks `fork/main`. Never push to `origin`.

## Layout

- `src/zpa/` — the real package (`pip install -e .` → `zpa-*` console scripts)
  - `audit_pyramid.py` — `audit_one(pm)`, check codes, severities
  - `zarrmeta.py` — `read_pyramid(store, root)` (header-only, fast)
  - `httpstore.py` — `open_store(base)` for https:// and s3://
  - `volcomp.py` — volcomp shard-index parsing + decode via vendored libvolcomp
  - `data/` — vendored `libvolcomp` decoder (Linux x86-64, MIT; see
    `src/zpa/data/VOLCOMP_PROVENANCE.md`); override with `$VOLCOMP_LIB`
- `bin/` — thin shims, kept for backward compatibility
- `tests/` — pytest suite (20 tests); keep it green
- `data/known-defects.json` — machine-readable defect kill list (generator:
  `zpa-known-defects`)
- `docs/` — GitHub Pages dashboard + September writeup
- `artifacts/` — dated campaign outputs; the evidence behind published numbers
- `workflows/audit.yml` — staged CI workflow (NOT active: enabling needs the
  maintainer to move it to `.github/workflows/`; do not move it yourself)

## Commands

```bash
zpa-audit --base https://dl.ash2txt.org/ --roots out/discover_zarr.roots.jsonl
zpa-gate --base <base> --roots new-roots.jsonl          # exits 1 on >= --fail-on
zpa-scan-chunks --base <base> --roots shortlist.jsonl   # sampled content probe
python -m pytest tests/ -q
```

## Hard-won lessons (do not re-learn)

1. **Missing ≠ empty ≠ zero-filled.** Three different things: absent from the
   shard index (masked background — legitimate), present-but-all-fill_value
   (the `CHUNK_SAMPLE_ALL_EMPTY` review flag), present-with-data. Conflating
   them is the #1 way to produce a false finding.
2. **Volcomp chunks decode over HTTP byte ranges.** Shard indexes are parsed
   with `zpa/volcomp.py`; never assume zarr-python can read them. The
   vendored decoder is Linux x86-64 only — on other platforms set
   `$VOLCOMP_LIB`.
3. **Full-v2 campaigns:** every level must be accounted for as decoded
   evidence, confirmed chunklessness, or explicit coverage gap. Never claim
   "all levels probed" without the coverage table.
4. **The `other/dev/meshes/` present-but-empty finding is a dev derivative,
   not a scroll** — medium severity, human review, with caveats. Don't
   upgrade it to high without new evidence.
5. **Severity is load-bearing.** `high` = do not train / do not publish.
   New high-severity checks need corpus-wide evidence.

## Working rules

- Branch from `main`; never force-push to `main`.
- New check codes need a unit test on a synthetic pyramid.
- Every number in docs/PRs must trace to a command + artifact in this repo.
- Add new defects to `data/known-defects.json` via the generator, not by hand.
- Opening PRs/issues, enabling CI, or publishing to PyPI needs the
  maintainer's explicit approval — prepare the branch, don't ship it.
