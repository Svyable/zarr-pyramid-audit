# External validation strategy

ZPA's own fixture corpus is intentionally adversarial toward the failure classes
ZPA was built to detect. That makes it useful for regression testing, but not
independent ground truth. External tools and external cases therefore serve
different roles and must be reported separately.

## Benchmark-ready tools

| tool | pinned source / release | role | what a fair comparison can claim | important limitation |
|---|---|---|---|---|
| zarr-python | project dependency / version recorded in each artifact | consumer baseline | whether ordinary opens and reads surface an error | successful reads do not imply structural integrity |
| ome-zarr-models | 1.7 | OME-NGFF metadata model | whether 0.4/0.5 metadata is accepted or rejected | validates metadata semantics, not chunk completeness |
| yaozarrs | 0.3.2 | OME-NGFF validator | whether metadata and declared hierarchy pass its validation | different scope from ZPA's transport/evidence model |
| zarr-lint | 0.0.3; upstream main checked at `19e27d07fbd4379ba6a3e74d56c18dd6e2233cab` | independent structural Zarr linter | which structural diagnostics it emits on the same local stores | remote HTTP discovery depends on consolidated metadata; otherwise only the root is inspected |

Run these through `fixtures/compare_baselines.py` using
`fixtures/requirements-baselines.txt`. New results go in a new dated artifact
directory. Do not rewrite the 2026-10-01 baseline artifact.

For zarr-lint, preserve rule IDs in the machine-readable output. Store-access
or internal tool errors are recorded separately and are neither counted as
findings nor converted to clean results. For remote tests, record discovery
coverage separately from diagnostics.

## Oztest: independent cases, not yet admissible evidence

The selected OME-Zarr 0.5 image cases are pinned in
`fixtures/external/oztest-pin.json` by repository commit and blob SHA. Their
expected validity comes from Oztest's own `valid/` and `invalid/` directory
classification, not from case names and not from ZPA.

They are not yet part of the benchmark:

- At the pinned commit, the Oztest repository root has no `LICENSE` file and
  `pyproject.toml` declares no license. The case contents are therefore not
  copied here and must not be used as Scroll Prize evidence until reuse terms
  are verified.
- Oztest labels itself alpha/work in progress and warns that cases may need
  correction.
- Its OME-Zarr 0.5 cases are `parse_attributes` cases, while its current
  hierarchy-level `validate_zarr` corpus is OME-Zarr 0.6. ZPA deliberately
  reports 0.6 as unmodelled rather than applying 0.4/0.5 conformance rules.
- Any future adapter from a v0.5 attribute object to a complete Zarr hierarchy
  must be documented and tested as an adapter. Adapter assumptions are not
  upstream ground truth.

This is why the repository pins references now but does not publish a score
against them yet.

## xzarrguard: strong completeness comparator, narrower domain

`xzarrguard` 0.1.2 (upstream main checked at
`f5d876a98a3db11b5da87283ec3a3bddc8e8021c`) is MIT-licensed and directly
checks expected chunk completeness, including remote stores through fsspec.
That makes it a meaningful independent comparator for ZPA's missing-chunk
failure class.

Its scope is narrower:

- Zarr v3 only.
- Python 3.12+.
- Its core question is completeness under its no-data policy, not OME-NGFF
  conformance, tri-state transport evidence, or sampled content semantics.

The fair comparison is therefore a **separate v3 completeness table**, not
adding xzarrguard to the all-fixture aggregate denominator. That harness is
`fixtures/compare_xzarrguard.py`; it records each applicable store's expected
chunk count, missing-unexpected count, allowed-missing count, manifest issues,
tool errors, and the corresponding ZPA integrity/codes.

```bash
# Python 3.12+
pip install -e .
pip install -r fixtures/requirements-completeness.txt
python fixtures/compare_xzarrguard.py --out-dir artifacts/YYYY-MM-DD-xzarrguard-comparison
```

## clearscale: compatibility baseline, not a defect detector

`clearscale` (upstream main checked at
`288fa33ccfb052e8627dc5d5faf2eed1ac238b5f`) is dual-licensed MIT /
Apache-2.0, dependency-free, and models multiscale metadata across OME-Zarr
versions. Its README describes active development and an unstable pre-1.0 API.

It is primarily a metadata construction/manipulation library rather than a
store-integrity validator. A useful comparison would be parse/round-trip
compatibility on clean metadata and deliberately malformed metadata, with
exceptions recorded verbatim. It should not be presented as competing with
ZPA's chunk-presence or transport-evidence checks.

## Reporting rule

Do not collapse unlike tools into one "accuracy" leaderboard. Publish:

1. per-case outputs,
2. applicability / discovery coverage,
3. exact versions or source commits,
4. the independent source of expected outcomes,
5. tool errors separately from findings,
6. known selection bias and adapter assumptions.

That evidence is more defensible to Scroll Prize reviewers than a larger but
ambiguous headline score.
