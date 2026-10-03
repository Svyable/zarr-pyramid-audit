"""Run yaozarrs on the live PHerc0814 defect and its populated sibling.

    pip install 'yaozarrs[io]' s3fs
    python artifacts/2026-10-03-baseline-yaozarrs/live_check.py

Same two roots as artifacts/2026-10-01-baseline-comparison/live_check.py.
validate_zarr_store() is what the `yaozarrs validate` CLI runs: metadata
plus structure (declared levels exist as arrays of matching ndim).
"""
import warnings

import yaozarrs

warnings.filterwarnings("ignore")
BASE = ("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/"
        "PHerc0814/segments/20260226123353-auto_grown_20260226123353106/"
        "surface-volumes/")
ROOTS = ["1.129um-0.22m-59keV-volume-20260521123630-L1.zarr",   # defective
         "2.399um-0.22m-78keV-volume-20260309142202.zarr"]      # populated sibling
for name in ROOTS:
    try:
        yaozarrs.validate_zarr_store(BASE + name)
        verdict = "accepts"
    except Exception as exc:  # noqa: BLE001
        verdict = f"rejects ({type(exc).__name__}: {str(exc).splitlines()[0]})"
    print(f"{name}\n  yaozarrs {yaozarrs.__version__} validate_zarr_store: {verdict}")

# Positive control: the validator must actually reach the store. A root that
# does not exist has to be rejected, or the two "accepts" above are vacuous.
try:
    yaozarrs.validate_zarr_store(BASE + "does-not-exist.zarr")
    print("control does-not-exist.zarr: accepts (CONTROL FAILED)")
except Exception as exc:  # noqa: BLE001
    print(f"control does-not-exist.zarr: rejects ({type(exc).__name__})")
