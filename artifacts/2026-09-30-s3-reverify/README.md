# Same-day re-verification — 2026-09-30 ~22:25 UTC

Re-ran the header-only audit against the defective PHerc0814 surface-volume
pyramid hours before the September Progress Prize deadline.

Result: **still defective** — 6 high-severity `LEVEL_NO_CHUNKS` findings, one
per level (L0–L5), identical signature to the 2026-09-29 campaign. The defect
has now been live and unrepaired for the full September window.

```bash
zpa-audit --base s3://vesuvius-challenge-open-data \
  --root "PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr" \
  --out-dir artifacts/2026-09-30-s3-reverify
```
