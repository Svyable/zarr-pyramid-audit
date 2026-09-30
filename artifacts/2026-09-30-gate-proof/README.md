# zpa-gate end-to-end proof — 2026-09-30

The publish-time gate fails closed on the defective pyramid and passes its
clean sibling, live against s3://vesuvius-challenge-open-data:

```bash
# rejects the defective root (exit 1)
zpa-gate --base s3://vesuvius-challenge-open-data \
  --root "PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr" \
  --fail-on high
# => gate: 0 pass, 1 fail out of 1 roots (threshold: high+), exit 1
#    log: gate-rejects-defective.log

# passes the clean sibling (exit 0)
zpa-gate --base s3://vesuvius-challenge-open-data \
  --root "PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes/1.129um-0.22m-59keV-volume-20260521123630.zarr" \
  --fail-on high
# => gate: 1 pass, 0 fail out of 1 roots (threshold: high+), exit 0
#    log: gate-passes-clean.log
```

This is the check that would have caught villa #1892 before publication.
