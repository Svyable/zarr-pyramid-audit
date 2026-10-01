"""List the tifxyz surfaces in the S3 bucket, from the 2026-09-29 crawl.

zpa-discover prunes *.tifxyz directories (rule 4), so the 2026-09-29 crawl
recorded their parents but not the surfaces. This lists every recorded
`mesh/` and `intermediate/` directory once and keeps children that end in
`.tifxyz` or are named `tifxyz_*` (the mesh/intermediate/tifxyz_original
layout). The output is the --roots input of the zpa-tifxyz run.

    AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com \
      python artifacts/2026-10-01-s3-tifxyz/enumerate.py > surfaces.jsonl

zpa-discover now writes discover_zarr.surfaces.jsonl directly; README.md
in this directory compares the two lists.
"""
import json
import posixpath
from concurrent.futures import ThreadPoolExecutor

from zpa.httpstore import open_store

store = open_store("s3://vesuvius-challenge-open-data/")
with open("artifacts/2026-09-29-s3/discover_zarr.dirs.jsonl", encoding="utf-8") as fh:
    dirs = [json.loads(line) for line in fh]
parents = [d["path"] for d in dirs if d["path"].endswith(("/mesh", "/intermediate"))]


def children(path):
    listing = store.list_dir_evidence(path)
    if listing.state != "PRESENT":
        raise SystemExit(f"listing {path}: {listing.state} {listing.reason}")
    return [posixpath.join(path, d) for d in listing.dirs
            if d.endswith(".tifxyz") or d.startswith("tifxyz_")]


with ThreadPoolExecutor(16) as pool:
    found = sorted(p for kids in pool.map(children, parents) for p in kids)
for root in found:
    print(json.dumps({"root": root}))
