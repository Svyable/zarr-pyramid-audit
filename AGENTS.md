# AGENTS.md — zarr-pyramid-audit

Instructions for AI coding agents working in this repo. Humans: the
contributing guide lives at `.github/CONTRIBUTING.md`.

## What this is

Corruption detection for OME-Zarr multiscale pyramids in the Vesuvius open
data: header-only audits, a publish-time gate, a sampled chunk-*content*
probe, and surface-evidence tools. "Don't train on lies." Companion:
[ScrolIQ](https://github.com/Svyable/scrollq) (capital I; formerly ScrollQ —
"find the bottleneck": scan-health triage plus open-problem diagnostics).
ScrolIQ depends on this repo, never the reverse; see "How this fits with
ScrolIQ" in the README.

**This is a fork** of [sgsllc-jr/zarr-pyramid-audit](https://github.com/sgsllc-jr/zarr-pyramid-audit)
(MIT). Upstream credit is retained in the README and LICENSE.

## Git remotes — read this first

- **Push only to `Svyable/zarr-pyramid-audit`** (ours).
- `sgsllc-jr/zarr-pyramid-audit` is upstream, read-only. Never push there.
- Remote *names* differ by clone — run `git remote -v` and trust the URL, not
  the name. Fresh clones (CI, cloud agent sessions) have `origin` → Svyable.
  A clone set up from the upstream fork may instead have `fork` → Svyable and
  `origin` → upstream.
- Branch from `main`; never force-push to `main`.

## Setup and commands

Python ≥ 3.11 (CI runs 3.11 and 3.12). Tests are network-free and take about
a second.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'                 # package + pytest + build
python -m pytest tests/ -q              # keep it green

zpa-discover --base https://dl.ash2txt.org/ --max-depth 10 --out-dir tmp
zpa-audit --base https://dl.ash2txt.org/ --roots tmp/discover_zarr.roots.jsonl --out-dir tmp
zpa-gate --base <base> --roots new-roots.jsonl          # exits 1 on >= --fail-on
zpa-scan-chunks --base <base> --levels-jsonl tmp/audit_pyramid.levels.jsonl --out-dir tmp
zpa-count-chunks --base <base> --from-findings tmp/audit_pyramid.findings.csv --code COMPRESSOR_DRIFT
# zpa-surface-support and zpa-surface-depth-profile: full examples in README.md
```

Every command takes `--help`; check flags there, not from memory. The tools
hit live public data (read-only, anonymous). Respect `--max-rps`. For `s3://`
bases set `AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com` (the global
endpoint is unreachable from some networks, including some sandboxes).

## Layout

- `src/zpa/` — the real package; `pyproject.toml` maps `zpa-*` scripts to it
  - `audit_pyramid.py` — `audit_one(pm)`; **`SEVERITY` is the single source of
    truth for check codes and their severities**
  - `zarrmeta.py` — `read_pyramid(store, root)` (header-only, fast)
  - `httpstore.py` — `open_store(base)` → `HttpStore` / `S3Store`; read-only,
    strict range reads, tri-state evidence results
  - `gate.py` — publish-time gate over `audit_one`
  - `discover_zarr.py`, `count_chunks.py` — root discovery; measured chunk counts
  - `chunkscan.py` + `scan_empty_chunks.py` — chunk-content probe (engine + CLI)
  - `volcomp.py` — volcomp shard-index parsing + decode via vendored libvolcomp
  - `surface_support.py`, `surface_depth_profile.py` — surface *evidence* tools
  - `runio.py` — `RunManifest`, CSV/JSONL writers, never-overwrite semantics
  - `pool.py` — bounded parallel map; captures per-item failures
  - `build_dashboard.py`, `build_known_defects.py` — generators (see below)
  - `data/` — vendored `libvolcomp` decoder (Linux x86-64, MIT; see
    `src/zpa/data/VOLCOMP_PROVENANCE.md`); override with `$VOLCOMP_LIB`
- `bin/` — thin shims for the original script names, kept for backward
  compatibility (not every command has one; new tools don't need one)
- `tests/` — pytest suite; offline, uses synthetic pyramids and fake stores.
  `test_docs_consistency.py` checks that documented flags exist, the README
  check-code list matches `SEVERITY`, and the dashboard describes every code —
  if it fails, fix the docs, don't delete the test.
- `data/known-defects.json` — machine-readable defect kill list
- `docs/` — GitHub Pages: `index.html` (**generated** by `build_dashboard.py`;
  edit the generator, never the HTML), and `september-2026.html`, which is
  hand-written and frozen at the 2026-09-30 evidence
- `artifacts/<date>-<name>/` — campaign outputs; the evidence behind
  published numbers. Each has a README/MD stating the command that made it.
- `issues/` — drafts of issues filed against ScrollPrize/villa (index in
  `issues/README.md`)
- `.github/workflows/` — `ci.yml`, `audit.yml`, `pages-check.yml` (live)
- `env.sh` — optional bootstrap inherited from the research toolkit (sets
  `RT_*`; `pool.py` reads `RT_WORKERS`). Not needed for normal work.
- **Downstream consumer:** ScrolIQ imports `zpa.httpstore.open_store`,
  `zpa.zarrmeta.read_pyramid`, `zpa.audit_pyramid.audit_one` and
  `zpa.volcomp`, and pins a tested commit of this repo in its
  `requirements-ci.txt`. Don't change those signatures or the finding fields
  (`code`, `severity`, `level`, `detail`) without checking it.

## What CI enforces (reproduce locally before pushing)

- `ci.yml` — builds sdist + wheel, installs the *wheel*, `pip check`, runs the
  tests, then runs **every console script with `--help`**. A new
  `[project.scripts]` entry must exit 0 on `--help`; new package data must
  live under a `package-data` glob (`src/zpa/data/*`).
- `pages-check.yml` — runs only when `docs/**`, `artifacts/**`,
  `data/known-defects.json` or the dashboard builder change. Regenerates the
  dashboard and `diff`s it against the committed `docs/index.html`, then
  checks local links. After touching any of those inputs run
  `python bin/build_dashboard.py` from the repo root (writes
  `docs/index.html`) and commit the result.
- `audit.yml` — live smoke test against the public S3 bucket (on pushes, PRs
  and weekly): audit sample, gate passes a known-clean pyramid, gate rejects a
  known-defective one, chunk probe smoke.

## Generated files — don't hand-edit

- `docs/index.html` ← `python bin/build_dashboard.py` (`zpa-dashboard`; run
  from the repo root or set `$ZPA_REPO`). Reads committed `artifacts/` and
  `data/known-defects.json`. The "updated" stamp is the newest
  `artifacts/<date>-*` directory, so output is reproducible.
- `data/known-defects.json` ← `zpa-known-defects`. It reads *hard-coded*
  artifact CSVs under `$ZPA_REPO` (default: cwd — run from the repo root); to
  record a new campaign, extend the list in `build_known_defects.py`, then
  regenerate. Regenerating bumps `generated_utc`; don't commit a run that
  changes nothing else.

## Adding a check code

1. Add it to `SEVERITY` in `audit_pyramid.py` (info-only codes go in
   `INFO_CODES`).
2. Unit test on a synthetic pyramid (see `tests/test_evidence_semantics.py`).
3. `high` needs corpus-wide evidence — see lesson 5.
4. Add it to the check-code list in `README.md` (with severity) and to
   `CODE_BLURB` in `build_dashboard.py`; regenerate the dashboard.
   `tests/test_docs_consistency.py` fails if either is out of sync.
5. Known defects it finds go in `data/known-defects.json` via the generator.

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
   New high-severity checks need corpus-wide evidence. ScrolIQ's per-volume
   verdict maps `high` → DO NOT TRAIN and `medium` → CAUTION (rules live in
   ScrolIQ; see the README), so changing a severity changes downstream verdicts.
6. **Absence needs positive evidence.** Header reads and listings are
   tri-state: `PRESENT` / `ABSENT` / `UNKNOWN`. Only a confirmed 404 supports
   an absence finding; timeouts, 403/429/5xx, unsupported listings and
   connection errors are `UNKNOWN` and must not become findings
   (`tests/test_evidence_semantics.py`).
7. **Range reads fail closed.** A short read, or a `Content-Range` that
   doesn't match the request, raises instead of returning partial bytes
   (`tests/test_httpstore.py`). Never loosen this to make a probe "work".
8. **The header-only audit stays `zarr`-free.** `audit_pyramid`, `zarrmeta`,
   `httpstore` and `gate` parse `.zattrs`/`.zarray`/`zarr.json` directly, so a
   store `zarr.open()` refuses can still be *reported*. Only the chunk probe
   and surface tools import `zarr`.
9. **Surface tools measure; they don't judge.** `zpa-surface-support` and
   `zpa-surface-depth-profile` emit evidence, not defect verdicts or quality
   scores — scoring belongs in ScrolIQ. Keep `--expected-volume-id` guards
   fail-closed.
10. **Claim discipline in docs.** Say what an artifact proves ("gate rejects X
    when run"), not more ("gate prevents Y"). Date-stamp live-state claims
    ("still live at 2026-09-30") and re-verify before restating them.

## Output hygiene

Tools never overwrite: an existing output is renamed `<name>.<timestamp>.bak`
first (`runio.py`; `*.bak` is git-ignored). Scratch runs go to `tmp/`
(ignored). Evidence worth keeping is copied into `artifacts/<date>-<name>/`
*deliberately*, with a README giving the exact command.

## Working rules

- Commits: short imperative subject, conventional prefix where it fits
  (`feat:` `fix:` `docs:` `test:` `ci:` `build:`), body says *why*. PRs are
  squash-merged, so write the PR title as the commit subject. Details in
  `.github/CONTRIBUTING.md`.
- Merge only on green CI at the PR's latest commit.
- New check codes need a unit test on a synthetic pyramid.
- Every number in docs/PRs must trace to a command + artifact in this repo.
- Add new defects to `data/known-defects.json` via the generator, not by hand.
- The maintainer's explicit approval is required before: opening PRs or
  issues (here, upstream, or on ScrollPrize/villa), adding or changing
  `.github/workflows/`, or publishing to PyPI. Prepare the branch; don't
  ship it.
