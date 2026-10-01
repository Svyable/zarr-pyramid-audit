# Contributing to zarr-pyramid-audit

Thanks for stopping by. This repo exists so nobody trains on lies: it finds
silently corrupt OME-Zarr pyramids in the Vesuvius open data before they
burn GPU time. Contributions that sharpen the detection — or the evidence
behind it — are welcome.

## Ways to contribute

- **Code**: new check codes, faster probes, better decoders.
- **Findings**: a defective pyramid we missed, a false positive we raised.
  Use the *data finding* issue template — evidence required (see below).
- **Docs**: the README, the dashboard copy, the September writeup.

## Setup

```bash
git clone https://github.com/Svyable/zarr-pyramid-audit.git
cd zarr-pyramid-audit
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'     # the package plus pytest and build
```

Python 3.11 or newer. (AI coding agents: also read [`AGENTS.md`](../AGENTS.md).)

## Running the tools

```bash
zpa-discover --base https://dl.ash2txt.org/ --max-depth 10 --out-dir tmp
zpa-audit --base https://dl.ash2txt.org/ --roots tmp/discover_zarr.roots.jsonl --out-dir tmp
zpa-gate --base https://dl.ash2txt.org/ --roots my-new-roots.jsonl   # publish-time gate
zpa-scan-chunks --base https://dl.ash2txt.org/ --levels-jsonl tmp/audit_pyramid.levels.jsonl --out-dir tmp
zpa-count-chunks --base https://dl.ash2txt.org/ --from-findings tmp/audit_pyramid.findings.csv --code COMPRESSOR_DRIFT
```

`zpa-surface-support` and `zpa-surface-depth-profile` have worked examples in
the [README](../README.md). Every command accepts `--help`. Run from the repo
root; scratch output goes in `tmp/` (git-ignored). For `s3://` bases, set
`AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com`.

Two generators write committed files — never hand-edit their output:

```bash
zpa-known-defects     # → data/known-defects.json (reads artifacts/ under the cwd)
zpa-dashboard         # → docs/index.html         (reads artifacts/ + known-defects)
```

(`bin/` holds thin shims over the real package in `src/zpa/`.)

## Tests

```bash
python -m pytest tests/ -q
```

All tests must pass before a PR is merged. They are network-free. New check
codes need a fixture in the corpus (`fixtures/`, see its README) with a
reviewed golden output; `tests/test_evidence_semantics.py` holds further
unit tests on synthetic pyramids and fake stores.

## The accuracy policy (read this)

A corruption detector that cries wolf is worse than none. Every claim in a
PR, issue, or doc change must be backed by something a reviewer can re-run:

- Numbers come from a command in this repo, with the artifact committed
  (or linked) so the run is reproducible.
- "Missing" chunks means absent from the shard index. Masked background is
  *legitimately* unstored — never report it as a defect.
- Severity is load-bearing: `high` means "do not train / do not publish."
  A new `high` check code needs corpus-wide evidence, not one anecdote.
- Known defects live in `data/known-defects.json` (machine-readable, with
  severity + provenance). Add yours there with the generator, not by hand.
- A failed or ambiguous read (timeout, 403, 429, 5xx, unsupported listing) is
  *unknown*, not *absent*. Only a confirmed 404 supports an absence finding.

## Pull requests

1. Branch from `main`: `git checkout -b <what>-<why>`.
2. Keep PRs small. One check code or finding per PR.
3. Update docs (README / dashboard / September page) if behavior changes. If
   you touch `artifacts/`, `data/known-defects.json` or the dashboard builder,
   regenerate `docs/index.html` with `zpa-dashboard` and commit it.
4. CI must be green. It runs: the test suite and a wheel-install smoke test of
   every `zpa-*` command (`ci.yml`); a dashboard-freshness and link check
   (`pages-check.yml`); and a live smoke audit against the public S3 bucket
   (`audit.yml`).
5. **Contract changes** (a check code added/removed/renamed, a severity, the
   report schema, the integrity states or the recommended verdicts) need a
   migration note in `CHANGELOG.md` quoting the new `contract-fingerprint`,
   a fixture in `fixtures/corpus.py` that exercises the change, and
   regenerated goldens (`python fixtures/corpus.py expected`) whose diff is
   reviewed. The tests enforce the first two; see `CHANGELOG.md`.

## Commits and merging

- **Commit messages:** a short imperative subject, with a conventional prefix
  where one fits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `build:`). Use the
  body for *why*, and cite the command/artifact behind any number it states.
- **One logical change per commit.** Don't mix a new check code with
  unrelated cleanups.
- **Merge method:** prefer **squash merge**, so the PR title becomes the commit
  subject on `main` (`Title (#N)`). Write the PR title as a good commit
  subject, and keep the description self-contained — it is the permanent
  record.
- **Merge only when CI is green** on the PR's latest commit (`ci.yml`,
  `audit.yml`, and `pages-check.yml` when it applies). Never force-push to
  `main`; delete the branch after merging.
- A change to `.github/workflows/` needs the maintainer's explicit approval.

## Reporting a data finding

Open an issue with the *data finding* template and include:

- the Zarr root and level,
- the exact command (flags included),
- what you expected vs. what you observed,
- the artifact (JSON/CSV) or a link to it.

Findings without a reproducible command will be asked for one.

## Upstream credit

This is a fork of [sgsllc-jr/zarr-pyramid-audit](https://github.com/sgsllc-jr/zarr-pyramid-audit)
(MIT). Upstream credit is retained; genuinely upstream fixes should be
proposed there too.

## License

By contributing, you agree your work is released under the MIT License.
