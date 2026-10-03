# Gate with the optional NGFF conformance field — 2026-10-03

First live run of `zpa-gate --ngff` (contract 1.3.0): the gate's integrity
verdict and yaozarrs' OME-NGFF verdict, side by side in one report.

```bash
pip install 'zarr-pyramid-audit[ngff]'          # yaozarrs 0.3.2
export AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com
P=PHerc0814/segments/20260226123353-auto_grown_20260226123353106/surface-volumes
zpa-gate --base s3://vesuvius-challenge-open-data --ngff \
  --root $P/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr \
  --root $P/2.399um-0.22m-78keV-volume-20260309142202.zarr \
  --out gate.json > gate.log            # exit 1
zpa-gate --base s3://vesuvius-challenge-open-data --ngff \
  --root $P/does-not-exist.zarr --out control.json > control.log   # exit 1
```

| root | gate (integrity) | `ngff_conformance.state` |
|---|---|---|
| `…-L1.zarr` (known defect) | **FAIL**, 6 × `LEVEL_NO_CHUNKS` (high) | conforms |
| `2.399um-…-20260309142202.zarr` | PASS | conforms |
| `does-not-exist.zarr` (positive control) | ABSENT (`ROOT_ABSENT`) | nonconformant (`FileNotFoundError`) |

What this shows: on a live defect, the two checks answer different questions.
The chunkless pyramid is spec-valid, and the gate still rejects it. The
control shows the validator read the bucket through the `s3://` → HTTPS
rewrite (`zpa.ngff.ngff_uri`), so the two "conforms" results are not
vacuous. The NGFF field is reported only and never changes the verdict.
