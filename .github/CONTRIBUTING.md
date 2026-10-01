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
pip install -e .
```

## Running the tools

```bash
zpa-discover --base https://dl.ash2txt.org/ --out-dir out/
zpa-audit --base https://dl.ash2txt.org/ --roots out/discover_zarr.roots.jsonl
zpa-gate --base https://dl.ash2txt.org/ --roots my-new-roots.jsonl   # publish-time gate
zpa-scan-chunks --base https://dl.ash2txt.org/ --roots shortlist.jsonl
zpa-dashboard --in out/ --out docs/index.html
zpa-known-defects --in out/ --out data/known-defects.json
```

(`bin/` holds thin shims over the real package in `src/zpa/`.)

## Tests

```bash
python -m pytest tests/ -q
```

All tests must pass before a PR is merged. New check codes need a fixture
in the corpus (`fixtures/`, see its README) with a reviewed golden output.

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

## Pull requests

1. Branch from `main`: `git checkout -b <what>-<why>`.
2. Keep PRs small. One check code or finding per PR.
3. Update docs (README / dashboard / September page) if behavior changes.
4. CI runs the test suite; green is required.
5. **Contract changes** (a check code added/removed/renamed, a severity, the
   report schema, the integrity states or the recommended verdicts) need a
   migration note in `CHANGELOG.md` quoting the new `contract-fingerprint`,
   a fixture in `fixtures/corpus.py` that exercises the change, and
   regenerated goldens (`python fixtures/corpus.py expected`) whose diff is
   reviewed. The tests enforce the first two; see `CHANGELOG.md`.

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
