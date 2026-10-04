# Named TIFXYZ content-tier gaps — 2026-10-03

This artifact closes the **inventory** half of October G3(a). It does not claim
that the 148 surfaces were content-decoded.

The source is the committed full S3 TIFXYZ survey from
`artifacts/2026-10-01-s3-tifxyz/tifxyz.findings.csv`, which ran the content
tier with a deliberate **32 MiB per-channel cap**. Every
`TIFXYZ_CONTENT_UNDECODED` row in that campaign is a size-cap row; none is a
codec/decoder failure.

## Frozen inventory

- surfaces with a content-tier cap gap: **148**
- smallest first-over-cap channel: **33,717,830 bytes**
- median: **89,833,822 bytes**
- p90: **367,527,350 bytes**
- p95: **409,581,278 bytes**
- largest: **464,276,814 bytes**
- above 64 MiB: **91**
- above 128 MiB: **43**
- above 256 MiB: **21**
- above 512 MiB: **0**

`gaps.csv` names every root, the first channel that exceeded the cap, and its
stored byte size. This makes the remaining content work explicit rather than
counting header-only surfaces as content-checked.

Rebuild deterministically from the Oct. 1 artifact:

```bash
python artifacts/2026-10-03-tifxyz-content-gaps/extract.py
git diff --exit-code artifacts/2026-10-03-tifxyz-content-gaps/gaps.csv
```

A future higher-cap or streaming campaign can consume this exact list. Until
then, these 148 remain **content evidence gaps**, not clean content results.
