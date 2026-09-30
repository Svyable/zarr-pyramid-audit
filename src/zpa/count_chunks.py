#!/usr/bin/env python3
"""
count_chunks.py -- MEASURE what a Zarr pyramid actually stores, level by level.

audit_pyramid.py is header-only: it can say "levels 1-5 are uncompressed" but it
can only *model* the storage cost from shape/chunks/dtype. That model is wrong
whenever a writer omitted empty chunks (write_empty_chunks=False), which is
common for sparse label/mask volumes. This tool replaces the model with a count:

  * lists every chunk key at each requested level (nested '/' or flat '.'),
    so `present_chunks` is exact, not ceil(shape/chunks);
  * HEADs a sample of present chunks to get real stored sizes and to confirm
    whether an uncompressed level stores every chunk at its full padded size;
  * GETs a small sample of present chunks and re-encodes them locally with
    blosc/zstd and blosc/lz4 to give a MEASURED compression ratio per level,
    so "recoverable bytes" is grounded in this volume's own data.

Requests: one listing per directory in the chunk tree of each requested level
(for a nested 128^3 pyramid that is a few thousand per volume at level 1,
tens at level 5), plus `--head-sample` HEADs and `--compress-sample` GETs per
level. Level 0 is excluded by default because its chunk tree is large; pass
--include-l0 to count it too.

Outputs (never overwritten; existing files are backed up first):
    count_chunks.levels.jsonl     one record per (root, level)
    count_chunks.roots.csv        per-root totals
    count_chunks.summary.json     corpus totals
    count_chunks.manifest.json    provenance

Usage:
    python bin/count_chunks.py --base https://dl.ash2txt.org/ \
        --from-findings tmp/audit_pyramid.findings.csv --code COMPRESSOR_DRIFT \
        --max-rps 30 --workers 16
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import re
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zpa.httpstore import open_store                                   # noqa: E402
from zpa.pool import parallel_map                                      # noqa: E402
from zpa.runio import CsvWriter, JsonlWriter, RunManifest, write_json  # noqa: E402
from zpa.zarrmeta import read_pyramid                                  # noqa: E402

_NUM = re.compile(r"^\d+$")
_FLAT = re.compile(r"^\d+(\.\d+)+$")

_ITEMSIZE = {
    "|u1": 1, "uint8": 1, "|i1": 1, "int8": 1, "|b1": 1, "bool": 1,
    "<u2": 2, ">u2": 2, "uint16": 2, "<i2": 2, ">i2": 2, "int16": 2, "<f2": 2, "float16": 2,
    "<u4": 4, ">u4": 4, "uint32": 4, "<i4": 4, ">i4": 4, "int32": 4, "<f4": 4, ">f4": 4, "float32": 4,
    "<u8": 8, "<i8": 8, "<f8": 8, "float64": 8, "int64": 8, "uint64": 8,
}


def itemsize(dtype) -> int | None:
    return _ITEMSIZE.get(str(dtype))


def is_uncompressed(compressor) -> bool:
    return compressor in (None, "", "none", "null") or str(compressor).lower() in ("none", "null")


def list_chunk_keys(store, level_url: str, ndim: int, sep: str, workers: int) -> list[str]:
    """Return every chunk key under a level directory as 'i/j/k' or 'i.j.k'."""
    if sep != "/":
        _, files = store.list_dir(level_url)
        return [f for f in files if _FLAT.match(f) or (ndim == 1 and _NUM.match(f))]
    # nested: walk ndim-1 directory levels, listing files at the last
    frontier = [""]
    for depth in range(ndim - 1):
        def _ls(prefix):
            dirs, _ = store.list_dir(f"{level_url}/{prefix}" if prefix else level_url)
            return [f"{prefix}/{d}" if prefix else d for d in dirs if _NUM.match(d)]
        nxt: list[str] = []
        for res in parallel_map(_ls, frontier, workers=workers, progress=False):
            if res.ok:
                nxt.extend(res.value)
        frontier = nxt
    keys: list[str] = []
    def _files(prefix):
        _, files = store.list_dir(f"{level_url}/{prefix}")
        return [f"{prefix}/{f}" for f in files if _NUM.match(f)]
    for res in parallel_map(_files, frontier, workers=workers, progress=False):
        if res.ok:
            keys.extend(res.value)
    return keys


def sample_evenly(keys: list[str], n: int) -> list[str]:
    if n <= 0 or not keys:
        return []
    if len(keys) <= n:
        return list(keys)
    step = len(keys) / n
    return [keys[int(i * step)] for i in range(n)]


def measure_level(store, root: str, lm, args) -> dict:
    rec = {
        "root": root, "level": lm.path, "index": lm.index,
        "shape": lm.shape, "chunks": lm.chunks, "dtype": lm.dtype,
        "compressor": lm.compressor, "uncompressed": is_uncompressed(lm.compressor),
        "dimension_separator": lm.dimension_separator,
        "grid_chunks": lm.n_chunks, "present_chunks": None, "present_fraction": None,
        "chunk_bytes_full": None, "head_sample_n": 0, "head_sizes": [],
        "all_sampled_full_size": None, "stored_bytes": None, "stored_bytes_basis": None,
        "compress_sample_n": 0, "ratio_zstd3": None, "ratio_lz4_5": None,
        "recoverable_bytes_zstd3": None, "error": None,
    }
    if not lm.present or not lm.shape or not lm.chunks:
        rec["error"] = lm.error or "level not present"
        return rec
    isz = itemsize(lm.dtype)
    ndim = len(lm.shape)
    full = (math.prod(lm.chunks) * isz) if isz else None
    rec["chunk_bytes_full"] = full
    level_url = f"{root}/{lm.path}"
    keys = list_chunk_keys(store, level_url, ndim, lm.dimension_separator, args.workers)
    rec["present_chunks"] = len(keys)
    if lm.n_chunks:
        rec["present_fraction"] = len(keys) / lm.n_chunks

    # HEAD sample -> real stored sizes
    hs = sample_evenly(keys, args.head_sample)
    sizes: list[int] = []
    for res in parallel_map(lambda k: store.head(f"{level_url}/{k}"), hs,
                            workers=args.workers, progress=False):
        if res.ok and res.value.exists and res.value.size is not None:
            sizes.append(int(res.value.size))
    rec["head_sample_n"] = len(sizes)
    rec["head_sizes"] = sizes
    if sizes and full:
        rec["all_sampled_full_size"] = all(s == full for s in sizes)
    if keys:
        if rec["uncompressed"] and full and rec["all_sampled_full_size"]:
            rec["stored_bytes"] = len(keys) * full
            rec["stored_bytes_basis"] = "exact: uncompressed, every sampled chunk is full padded size"
        elif sizes:
            rec["stored_bytes"] = int(statistics.mean(sizes) * len(keys))
            rec["stored_bytes_basis"] = f"estimate: mean of {len(sizes)} HEAD sizes x present chunks"

    # GET sample -> measured compressibility
    if args.compress_sample > 0 and keys and rec["uncompressed"]:
        try:
            from numcodecs import Blosc
        except Exception as e:  # pragma: no cover
            rec["error"] = f"numcodecs unavailable: {e}"
            return rec
        cs = sample_evenly(keys, args.compress_sample)
        raw_tot = z_tot = l_tot = 0
        for res in parallel_map(lambda k: store.get(f"{level_url}/{k}"), cs,
                                workers=min(args.workers, 4), progress=False):
            if not res.ok:
                continue
            raw = res.value
            try:
                import numpy as _np
                buf = _np.frombuffer(raw, dtype=_np.dtype(lm.dtype)) if lm.dtype else raw
            except Exception:
                buf = raw  # fall back to typesize=1 if dtype is unparseable
            z = Blosc(cname="zstd", clevel=3, shuffle=Blosc.BITSHUFFLE).encode(buf)
            l4 = Blosc(cname="lz4", clevel=5, shuffle=Blosc.SHUFFLE).encode(buf)
            raw_tot += len(raw); z_tot += len(z); l_tot += len(l4)
        rec["compress_sample_n"] = len(cs)
        if raw_tot and z_tot and l_tot:
            rec["ratio_zstd3"] = raw_tot / z_tot
            rec["ratio_lz4_5"] = raw_tot / l_tot
            if rec["stored_bytes"]:
                rec["recoverable_bytes_zstd3"] = int(rec["stored_bytes"] * (1 - z_tot / raw_tot))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--root", action="append", default=[], help="pyramid root (repeatable)")
    ap.add_argument("--from-findings", help="audit_pyramid.findings.csv to draw roots from")
    ap.add_argument("--code", default="COMPRESSOR_DRIFT", help="finding code to select roots by")
    ap.add_argument("--levels", default=None, help="comma list of level paths; default = all except 0")
    ap.add_argument("--include-l0", action="store_true")
    ap.add_argument("--head-sample", type=int, default=6)
    ap.add_argument("--compress-sample", type=int, default=3)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--max-rps", type=float, default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    roots = list(dict.fromkeys(args.root))
    if args.from_findings:
        with open(args.from_findings, newline="") as fh:
            for r in csv.DictReader(fh):
                if r["code"] == args.code and r["root"] not in roots:
                    roots.append(r["root"])
    if not roots:
        ap.error("no roots given (--root or --from-findings)")

    out_dir = args.out_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp")
    store = open_store(args.base, timeout=args.timeout, max_rps=args.max_rps)
    want = set(args.levels.split(",")) if args.levels else None

    with RunManifest("count_chunks", out_dir) as man, \
         JsonlWriter(os.path.join(out_dir, "count_chunks.levels.jsonl")) as lv_out, \
         CsvWriter(os.path.join(out_dir, "count_chunks.roots.csv"),
                   ["root", "levels_counted", "present_chunks", "grid_chunks",
                    "stored_bytes", "stored_gb", "recoverable_gb_zstd3", "basis"]) as csv_out:
        man.set("roots", roots)
        tot_stored = tot_recov = 0
        codes = Counter()
        for root in roots:
            pm = read_pyramid(store, root)
            levels = [l for l in pm.levels if l.present and
                      (want is None and (args.include_l0 or l.path != "0") or (want and l.path in want))]
            print(f"\n== {root}  ({len(levels)} levels)", file=sys.stderr, flush=True)
            r_store = r_recov = r_pres = r_grid = 0
            bases = set()
            for lm in levels:
                rec = measure_level(store, root, lm, args)
                lv_out.write(rec)
                pf = rec["present_fraction"]
                sb = rec["stored_bytes"]; rz = rec["ratio_zstd3"]
                stored_s = f"{sb/1e9:.2f}GB" if sb else "n/a"
                zstd_s = f"{rz:.2f}x" if rz else "n/a"
                if pf is not None:
                    head = f"   L{lm.path}: present={rec['present_chunks']}/{rec['grid_chunks']} ({pf:.1%})"
                else:
                    head = f"   L{lm.path}: {rec['error']}"
                print(f"{head} stored={stored_s} zstd3={zstd_s}", file=sys.stderr, flush=True)
                if rec["stored_bytes"]:
                    r_store += rec["stored_bytes"]; r_recov += rec["recoverable_bytes_zstd3"] or 0
                    bases.add((rec["stored_bytes_basis"] or "").split(":")[0])
                r_pres += rec["present_chunks"] or 0; r_grid += rec["grid_chunks"] or 0
                man.count("levels_measured")
                if rec["error"]:
                    man.count("level_errors")
            csv_out.write({"root": root, "levels_counted": len(levels), "present_chunks": r_pres,
                           "grid_chunks": r_grid, "stored_bytes": r_store,
                           "stored_gb": round(r_store / 1e9, 3),
                           "recoverable_gb_zstd3": round(r_recov / 1e9, 3),
                           "basis": "+".join(sorted(bases))})
            tot_stored += r_store; tot_recov += r_recov
            man.count("roots_measured")
        summary = {"roots": len(roots), "stored_bytes": tot_stored, "stored_gb": round(tot_stored / 1e9, 3),
                   "recoverable_gb_zstd3": round(tot_recov / 1e9, 3)}
        p = write_json(os.path.join(out_dir, "count_chunks.summary.json"), summary)
        man.add_output(p, "corpus totals")
        for k, v in summary.items():
            man.set(k, v)
        print(f"\nTOTAL stored={summary['stored_gb']} GB  recoverable(zstd3)={summary['recoverable_gb_zstd3']} GB",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
