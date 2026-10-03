# Reproducibility

This document defines the minimum clean-room reproduction path for
`zarr-pyramid-audit`.

## Supported environment

- Python 3.11 or newer.
- CI currently exercises Python 3.11 and 3.12.
- Network-free tests use synthetic/local fixtures.
- Live commands may read public HTTP or S3 data.
- The vendored volcomp decoder is Linux x86-64; other platforms may provide
  `VOLCOMP_LIB=/path/to/libvolcomp.so`.

## Clean checkout

```bash
git clone https://github.com/Svyable/zarr-pyramid-audit.git
cd zarr-pyramid-audit
git checkout <40-hex-commit>

python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,tifxyz]'

python -m pytest tests/ -q
```

The package metadata in `pyproject.toml` is authoritative. Published
evidence should always record the exact Git commit and installed dependency
versions rather than relying on a moving branch.

## Offline behavioral reproduction

The fixture corpus is the fastest deterministic proof that the installed code
matches the repository's documented semantics:

```bash
python fixtures/corpus.py build
python -m pytest tests/test_fixture_corpus.py -q
zpa-gate --base fixtures/zarr --root clean_v2.zarr --root missing_level.zarr
```

Expected fixture outputs are committed so semantic changes appear as a
reviewable diff.

## Live-data reproduction

Live evidence must record:

- the exact command and flags;
- Git commit;
- Python and dependency versions;
- source URL / S3 root;
- UTC execution time;
- output hashes or committed artifact directory;
- any environment variables that affect data access.

For S3-based Vesuvius data:

```bash
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
```

A network failure is not evidence that data are absent. The code keeps
unobservable evidence as `UNKNOWN` and fails closed where required.

## Reproducing published claims

Every durable numeric claim should point to a dated directory under
`artifacts/` containing the command and output. Do not silently replace a
published run in place; create a new dated campaign and explain the difference.

## Submission-grade use

For Vesuvius Challenge / Scroll Prize work, treat ZPA as an input-integrity and
provenance component, not as proof of legibility or complete unrolling.
Submission-level reproduction should additionally pin the downstream ScrolIQ
commit, container digest, exact eligible CT identity, meshes/renders, model
checkpoints, region exclusions, seeds, and held-out validation evidence.
