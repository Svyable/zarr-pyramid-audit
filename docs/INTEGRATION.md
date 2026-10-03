# Integrating zarr-pyramid-audit

**ZPA produces evidence; the consuming workflow owns the decision.** The gate
makes a policy easy to enforce, but neither the gate nor a clean report proves
a dataset is fit to train on. Both only say that the checks ZPA runs found
nothing at the chosen severity *and* that the evidence those checks needed was
actually observed.

## Three ready-to-use recipes

| need | recipe | what it does |
|---|---|---|
| Block a CI job on a bad root | [`examples/github-actions/zarr-gate.yml`](../examples/github-actions/zarr-gate.yml) | a `zarr-gate` job audits the published roots (header-only), annotates findings, uploads the JSON report; the downstream job `needs:` it |
| Check before you upload, train or publish | [`examples/preflight.sh`](../examples/preflight.sh) | `zpa-gate` on a local staging directory or any store, writes `zpa-preflight.json`, exits 1 on high severity, unreadable evidence or a missing root |
| Gate tifxyz surfaces before use | `zpa-tifxyz --base <store> --roots discover_zarr.surfaces.jsonl --content --fail-on medium --out-dir out/` | exits 1 when a surface has a medium finding or `UNKNOWN` integrity; one schema'd report per surface in `tifxyz.reports.jsonl` |
| Feed a ranking / training pipeline | [`examples/python_api.py`](../examples/python_api.py) | calls `zpa.report.audit_root`, applies an example policy (drop FAIL/UNKNOWN, down-weight WARN) and keeps the evidence attached to each decision |

All three run offline against the committed fixture corpus, and
`tests/test_integration_surface.py` runs the preflight script and the Python
example, and checks that every `zpa-gate` flag in the workflow example exists.

`zpa-gate` exit codes: `0` every root passed · `1` a finding at or above
`--fail-on`, evidence that could not be observed (`GATE_UNREADABLE`), or a root
that does not exist / is empty (`GATE_ROOT_ABSENT`) · `2` usage error. The two
escape hatches, `--ignore-unreadable` and `--allow-absent`, are explicit
policy choices. Do not set them by default.

## The report (schema 1.x)

`zpa.report.audit_root(store, root)` and `zpa-gate --out` (one per root)
emit a report validated by
[`src/zpa/data/audit-report.schema.json`](../src/zpa/data/audit-report.schema.json)
(JSON Schema 2020-12, shipped in the wheel). Branch on `integrity`:

| `integrity` | meaning | recommended consumer verdict |
|---|---|---|
| `FAIL` | at least one `high` finding: confirmed structural defect | DO NOT TRAIN |
| `UNKNOWN` | no `high` finding, but no clean verdict can be issued: required evidence was not observed (timeout, 401/403, 429, 5xx, connection error) or there is nothing to audit (`ROOT_ABSENT`, `EMPTY_ZARR_DIR`) | DO NOT TRAIN (fail closed, like the gate) |
| `WARN` | a `medium` finding, all required evidence observed | CAUTION |
| `PASS` | nothing above `low`, all required evidence observed | defer to the consumer's own scoring |

Precedence is `FAIL` > `UNKNOWN` > `WARN` > `PASS`. A confirmed defect makes the
volume bad regardless of what else could not be read, and missing evidence
rules out any clean verdict.

**Why `UNKNOWN` needs its own state.** `ACCESS_UNKNOWN` is severity `info` and
`ROOT_ABSENT` is `low`, by design: they describe the observation, not a
defect. A consumer that only looks for `high`/`medium` findings will
therefore read a 503, a 403 or a mistyped path as clean. Use `integrity`, or
apply the same rule yourself. `tests/test_contract.py` checks every
combination of severity and evidence state: anything with UNKNOWN evidence maps
to DO NOT TRAIN.

Each finding carries the evidence it rests on:

| `evidence_state` | finding is derived from |
|---|---|
| `PRESENT` | metadata that was read successfully (shape/scale/dtype checks, unreadable-but-present metadata) |
| `ABSENT` | confirmed absence: a 404, or a listing that provably shows the header but no chunk keys |
| `UNKNOWN` | an observation that failed. Never converted into absence or emptiness |

`coverage` records optional evidence that was not observed, mainly
chunk-presence listings on stores without an autoindex (`chunk_presence.UNKNOWN`
with a per-level `chunk_evidence_reason`). A coverage gap does not change
`integrity`, but it is reported so that "not checked" is never read as
"checked and fine". `has_chunks` is tri-state: `null` means "not observable",
never "no chunks".

The sampled chunk-content probe (`zpa-scan-chunks`) is separate evidence with
its own codes. Its only non-informational flag, `CHUNK_SAMPLE_ALL_EMPTY`, is
`medium` (a review flag). It reports a sample and does not prove the whole
volume is populated.

### tifxyz surfaces

`zpa.tifxyz.audit_surface(store, root, content=...)` and `zpa-tifxyz`
(`tifxyz.reports.jsonl`, one per surface) emit a second report kind,
`"kind": "tifxyz"`, validated by
[`src/zpa/data/tifxyz-report.schema.json`](../src/zpa/data/tifxyz-report.schema.json).
It shares `schema_version`, the finding fields, the evidence states and the
`integrity` rules with the pyramid report, so the same consumer policy
applies unchanged. `zpa.report.validate_report(report)` picks the schema by
`kind`. The `surface` block records the grid, the declared metadata, the
valid-point fraction, the stored-coordinate bbox, whether the content tier
actually ran (`content_checked`), and which decoder produced it.

## ScrolIQ integration surface

[ScrolIQ](https://github.com/Svyable/scrollq) depends on this repo (never the
reverse) and pins a tested commit in its `requirements-ci.txt`. The surface it
may rely on:

| surface | stability |
|---|---|
| `zpa.httpstore.open_store(base_url, **kw)` | stable; also accepts `file://` and plain paths since 1.0.0 |
| `zpa.zarrmeta.read_pyramid(store, root, ...)` | stable |
| `zpa.audit_pyramid.audit_one(pm)` → `(findings, level_records, pyramid_record)`; finding fields `code`, `severity`, `level`, `detail` | stable |
| `zpa.volcomp` (shard-index parsing, vendored decoder) | stable |
| `zpa.report.audit_root`, `build_report`, `integrity_of`, `consumer_verdict`, `SCHEMA_VERSION`, `contract()` | **new in contract 1.0.0**; versioned by `schema_version` |
| `src/zpa/data/audit-report.schema.json` | versioned by `schema_version` (semver) |
| `zpa.tifxyz.audit_surface`, `src/zpa/data/tifxyz-report.schema.json` | **new in contract 1.2.0**; same `schema_version` |
| `zpa.ngff.check_ngff`, report field `ngff_conformance`, `zpa-gate --ngff` | **new in contract 1.3.0**; optional `[ngff]` extra (yaozarrs); reported only, never changes `integrity` or the gate verdict |

`tests/test_contract.py` pins the signatures and finding fields above.

**Verdict mapping, ZPA side vs. ScrolIQ.** Until 2026-10-01, ScrolIQ's
`scrollq-health` ([`health.py`](https://github.com/Svyable/scrollq/blob/main/src/scrollq/health.py),
read at `6ea1a33`) counted severities only: `high` → DO NOT TRAIN, `medium` →
CAUTION, otherwise it fell through to its quality score. That failed open on
missing evidence. [Svyable/scrollq#55](https://github.com/Svyable/scrollq/pull/55)
switches it to `zpa.report.audit_root` and this contract's
`RECOMMENDED_CONSUMER_VERDICT`, and pins this repo at `e473afd`:

| situation | ZPA `integrity` / recommended | ScrolIQ at `6ea1a33` | ScrolIQ after #55 |
|---|---|---|---|
| `high` finding | FAIL / DO NOT TRAIN | DO NOT TRAIN ✓ | DO NOT TRAIN ✓ |
| `medium` finding | WARN / CAUTION | CAUTION ✓ | CAUTION ✓ |
| a level returns 503/403/timeout (`ACCESS_UNKNOWN`, info) | UNKNOWN / DO NOT TRAIN | integrity `PASS`; **can be TRAIN** if the sampled level is readable | DO NOT TRAIN ✓ |
| root does not exist (`ROOT_ABSENT`, low) | UNKNOWN / DO NOT TRAIN | integrity `PASS`; quality unscorable, so CAUTION | DO NOT TRAIN ✓ (live negative control) |
| the audit raises | (never: `audit_root` returns `AUDIT_ERROR`, FAIL) | `integrity_error` recorded, findings empty, integrity `PASS` | FAIL → DO NOT TRAIN ✓ |

The live evidence for the right-hand column, including the absent-root
negative control and the three unchanged published verdicts, is in ScrolIQ's
[`artifacts/2026-10-01-health-verdicts-fail-closed/`](https://github.com/Svyable/scrollq/tree/main/artifacts/2026-10-01-health-verdicts-fail-closed).
ScrolIQ owns that policy. This repo pins its recommendation in
`RECOMMENDED_CONSUMER_VERDICT` and tests it.

## Versioning and change control

Check codes, severities, the schema and the verdict mapping form the
contract. A change needs a migration note in [`CHANGELOG.md`](../CHANGELOG.md)
quoting the new `contract-fingerprint` (enforced by `tests/test_contract.py`),
plus a fixture update with reviewed goldens (enforced by
`tests/test_fixture_corpus.py`, which fails when a check code has no fixture).
See [`fixtures/README.md`](../fixtures/README.md).
