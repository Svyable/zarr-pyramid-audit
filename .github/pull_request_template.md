## What

<!-- One check code or finding per PR. -->

## Evidence

<!-- Commands run + artifacts. Every number must trace to something reproducible. -->

## Severity justification (new/changed check codes)

- [ ] Corpus-wide evidence (not one anecdote) for `high` severity
- [ ] `data/known-defects.json` updated via `zpa-known-defects` if applicable

## Docs

- [ ] README / dashboard / September page updated if behavior changed
- [ ] `tests/` updated; `python -m pytest tests/ -q` green

## Checklist

- [ ] Small, single-purpose PR branched from `main`
- [ ] Missing ≠ empty ≠ zero-filled (masked background is legitimate)
- [ ] Upstream fix proposed to sgsllc-jr/zarr-pyramid-audit if generally applicable
- [ ] Follows `.github/CONTRIBUTING.md`
