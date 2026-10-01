"""Run the two baselines on the live PHerc0814 defect and its populated sibling.

    pip install ome-zarr-models
    AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com \
      python artifacts/2026-10-01-baseline-comparison/live_check.py

For each root: does ome-zarr-models accept the metadata, and what does a
zarr-python read of a 64^3 window of level 5 return (and does it raise)?
"""
import warnings

import numpy as np
import s3fs
import zarr
from ome_zarr_models import open_ome_zarr
from zarr.storage import FsspecStore

warnings.filterwarnings("ignore")
P = ("vesuvius-challenge-open-data/PHerc0814/segments/"
     "20260226123353-auto_grown_20260226123353106/surface-volumes/")
ROOTS = ["1.129um-0.22m-59keV-volume-20260521123630-L1.zarr",   # defective
         "2.399um-0.22m-78keV-volume-20260309142202.zarr"]      # populated sibling
fs = s3fs.S3FileSystem(anon=True, client_kwargs={
    "endpoint_url": "https://s3.us-east-1.amazonaws.com"})
for name in ROOTS:
    group = zarr.open_group(FsspecStore.from_mapper(fs.get_mapper(P + name),
                                                    read_only=True), mode="r")
    try:
        verdict = f"accepts ({type(open_ome_zarr(group)).__name__})"
    except Exception as exc:  # noqa: BLE001
        verdict = f"rejects ({type(exc).__name__})"
    arr = group["5"]
    try:
        win = arr[tuple(slice(0, min(64, s)) for s in arr.shape)]
        read = (f"read {win.size} voxels, nonzero={int(np.count_nonzero(win))}, "
                f"raised=False")
    except Exception as exc:  # noqa: BLE001
        read = f"raised {type(exc).__name__}"
    print(f"{name}\n  ome-zarr-models: {verdict}\n"
          f"  zarr-python level 5 {arr.shape} {arr.dtype}: {read}")
