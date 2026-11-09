# State-machine inventory — zarr-pyramid-audit

This file maps implicit lifecycle and UI state to the code that owns it. It
does **not** redefine any audit code, severity, output schema, or ScrolIQ
consumer contract. These tools are read-only with respect to scientific input
volumes; a dashboard view is not an integrity verdict.

| Machine | Relevant states / transitions | Owner | Non-negotiable invariant |
| --- | --- | --- | --- |
| Store access | present / absent / unknown, with HTTP transient errors and bounded retries | `httpstore.py` | An inaccessible root is not a proved-absent root; network failures must not become clean data |
| Root discovery | candidate -> identified Zarr/other -> recorded | `discover_zarr.py`, `zarrmeta.py` | Unknown/headerless cases remain visible in evidence |
| Pyramid metadata | not inspected -> PASS/WARN/UNKNOWN/FAIL with findings | `zarrmeta.py`, `audit_pyramid.py`, `report.py` | `SEVERITY` and the versioned report schema define the published semantics |
| Content sampling | unscanned -> sample attempted -> decoded/fill/unknown/error | `chunkscan.py`, `scan_empty_chunks.py` | Header health cannot be substituted for decoded content evidence |
| Publication gate | pending -> pass/block/error | `gate.py` | A missing, unreadable, or severe structural defect fails closed at the chosen threshold |
| TIFXYZ surface | metadata -> TIFF headers -> optional decoded-content check -> report | `tifxyz.py` | Undecodable content is not silently treated as clean content |
| Evidence writers | path absent/existing -> backup -> opened -> buffered/flushed/closed -> manifest | `runio.py` | Prior output is backed up, not silently overwritten; partial JSONL is readable |
| Parallel survey workers | queued -> running -> success/failure result -> collected | `pool.py` | Per-root exceptions remain explicit results, not silently dropped |
| Public dashboard | default, filtered, sorted (orthogonal) -> reset | `build_dashboard.py` and `docs/index.html` | Sorting/filtering never alters evidence; only supported sort/severity values are accepted |

## Applied view-state contract

The public findings table now has one canonical `view` object with
`sortKey`, `ascending`, `severity`, and `query`. Events pass through
`transition(kind, value)`; unknown events throw, unsupported sorts/filters
are ignored, and reset returns to published defaults. One render path updates
the rows, active buttons, `aria-pressed`, `aria-sort`, and sort indicator.

Valid view state is round-trippable in `sort`, `dir`, `sev` and `q`
URL parameters. State updates replace the current history entry, preserve
unrelated query parameters and anchors, and degrade to local UI-only behavior
when history updates are restricted. Sort headers support Enter and Space,
and the table has an explicit reset button, `/` search shortcut, and Escape
reset. Data, audit reports, check severities and the publish gate are unchanged.

`tests/test_dashboard_state_contract.py` prevents generator/published-page
drift and locks core UI transition and accessibility hooks. Existing
`tests/test_dashboard.py` guards severity descriptions and evidence panels.

## Next steps for DX and AX

Treat input availability, evidence sufficiency, policy eligibility and
presentation as **different** machines. A worker returning does not mean an
audit passed; a successful audit does not authorize a ScrolIQ TRAIN verdict
without its own checks. A future deeper refactor may extract retry/terminal
states from `httpstore.py` and persisted run lifecycle from `runio.py`,
but it must be proven equivalent against the existing error fixtures and
`zpa.report` schema before it can replace behavior. The companion
`Svyable/scrollq` consumes the audit APIs, never vice versa.
