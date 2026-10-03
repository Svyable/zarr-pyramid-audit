# Contributing to zarr-pyramid-audit

Thank you for helping make Vesuvius Challenge data and submission evidence more trustworthy.

The detailed contribution policy lives in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). Read that file and [`AGENTS.md`](AGENTS.md) before changing audit semantics, evidence contracts, generated artifacts, or release workflows.

## Quick setup

```bash
git clone https://github.com/Svyable/zarr-pyramid-audit.git
cd zarr-pyramid-audit
python -m venv .venv
. .venv/bin/activate
python -m pip install -r reqs.txt
python -m pytest tests/ -q
```

Python 3.11 or newer is required. `pyproject.toml` is authoritative for package metadata and dependencies; `reqs.txt` is a contributor convenience entry point.

## Contribution standard

Contributions should be reproducible, evidence-backed, deterministic where randomness is involved, and fail closed when required evidence cannot be observed. New findings need a re-runnable command and a committed or linked artifact. New high-severity checks need corpus-wide evidence and fixtures. Do not turn ambiguous reads into absence claims, and do not weaken the distinction between missing, empty, and unreadable data.

For work intended to support a Vesuvius Challenge / Scroll Prize submission, preserve exact source-volume provenance, training/prediction separation, fixed seeds, public experiment records where models are trained, and machine-checkable traceability from inputs to reviewer outputs. The current prize rules are published at https://scrollprize.org/prizes.

## Pull requests

Branch from `main`, keep changes narrowly scoped, and run the full relevant test suite before proposing a merge. The repository-local policy in `.github/CONTRIBUTING.md` controls CI, generated-file, contract-migration, and merge requirements.

## Credit and licensing

Please add material upstream projects, datasets, or community work you rely on to [`CREDITS.md`](CREDITS.md) when appropriate. Do not remove existing upstream attribution.

By contributing, you agree that your contribution is made available under the repository's [MIT License](LICENSE). Third-party code and data remain subject to their own licenses and terms.
