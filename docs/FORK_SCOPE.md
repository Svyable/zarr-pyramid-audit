# Fork scope and attribution

**Status:** attribution and scope note, 2026-10-02.

This repository is a fork of [sgsllc-jr/zarr-pyramid-audit](https://github.com/sgsllc-jr/zarr-pyramid-audit), released under the MIT License. The fork relationship is part of the technical story, not something to hide.

## What came from the original project

The upstream project established the core idea and initial implementation of a **read-only, header-first integrity auditor for OME-Zarr multiscale pyramids**. In particular, upstream already included:

- direct parsing of Zarr metadata rather than depending on `zarr.open()` for the header audit;
- detection of silent multiscale failure classes such as missing levels, chunkless levels, scale/shape mismatches and metadata drift;
- positive-evidence semantics for absence rather than treating an unreachable object as missing;
- reproducible run manifests and non-overwriting outputs;
- the original `dl.ash2txt.org` corpus campaign and its published findings.

Those are upstream contributions and should be credited as such.

## What the Svyable fork adds

The claim for this fork is the extension of that auditor into a broader, submission-oriented evidence layer. Additions in the Svyable branch include, among other work:

- a versioned machine-readable report contract and schema, source-attestation hash, and fail-closed `zpa-gate`;
- sampled chunk-content probing, including volcomp-sharded data support and checksum evidence;
- OME-Zarr / S3 campaign expansion beyond the original host and dated whole-corpus re-audits;
- native TIFXYZ surface auditing with header/content evidence tiers;
- exact-volume Grand Prize CT preflight and surface-input evidence tools;
- comparisons against standard Zarr / OME-NGFF validators on the same fixtures and live defect;
- downstream integration with [ScrolIQ](https://github.com/Svyable/scrollq), where ZPA evidence can block training or submission work when integrity is failed or unknown.

See the [CHANGELOG](../CHANGELOG.md), [integration contract](INTEGRATION.md), [submission evidence map](SUBMISSION.md), and dated [artifacts](../artifacts/) for the implementation and evidence behind those extensions.

## Claim discipline

Use this wording when describing the project externally:

> Based on the original `sgsllc-jr/zarr-pyramid-audit`. The Svyable fork extends the read-only OME-Zarr auditor with versioned evidence contracts, fail-closed gating, content probes, TIFXYZ surface coverage, exact-volume Grand Prize preflight, validator comparisons, and downstream ScrolIQ integration.

Do not claim authorship of the original auditor, its basic header-only design, or its original corpus findings.

## Why this matters for Vesuvius Challenge review

The fork is most useful as a preflight and provenance component of a larger unrolling pipeline. It can establish that the bytes and metadata consumed by geometry and ink stages are the bytes the pipeline claims to have used. It cannot establish correct sheet identity, a correct unrolling, or readable ink by itself.

That bounded role is enough: it prevents storage or provenance failures from being laundered into stronger downstream evidence, while leaving geometry and ink quality to tools that directly measure those properties.
