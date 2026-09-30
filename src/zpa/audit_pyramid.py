#!/usr/bin/env python3
"""
audit_pyramid.py -- corpus-wide integrity audit of OME-Zarr multiscale pyramids.

WHY THIS EXISTS
Every consumer that is not doing full-resolution work reads a *reduced* level:
viewers navigate at level 3-5, registration and QC run at level 2, and several
published models are trained on a specific level. A pyramid level that is
absent, mis-declared, or generated with a different convention from its
siblings does not raise an error anywhere -- it returns plausible-looking
voxels. That is the whole failure class this tool measures.

Checks are header-only by default: a pyramid is judged from its .zattrs plus
one .zarray per level -- a few KB regardless of array size -- so the whole
corpus can be audited without downloading it.

CHECK CODES
  NOT_A_ZARR_GROUP   [info] no .zgroup/zarr.json and nothing Zarr-like inside
  BARE_ARRAY         [info] valid single-scale Zarr array (has .zarray); not a pyramid
  HEADERLESS_CHUNK_STORE  chunk keys present but no .zarray/.zgroup -- undecodable
  CONTAINER_NO_GROUP_HEADER  children are Zarr nodes but root has no group header;
                     zarr.open() on the *.zarr path fails
  EMPTY_ZARR_DIR     *.zarr directory with no contents
  NOT_MULTISCALE     [info] valid Zarr group, but not an OME pyramid
  MULTISCALE_EMPTY   declares multiscales but yields no usable datasets
  LEVEL_MISSING      level declared in multiscales has no readable array header
  LEVEL_NO_CHUNKS    level has a valid array header but holds NO chunk keys --
                     every read returns fill_value, no client raises an error
  LEVEL_UNDECLARED   numeric level directory exists but is not declared
  SCALE_NONMONOTONIC declared scales do not strictly increase with depth
  SCALE_SHAPE_MISMATCH  shape matches neither ceil nor floor of base/factor
  MIXED_ROUNDING     pyramid uses ceil at some levels and floor at others
  DTYPE_DRIFT        dtype changes between levels
  FILL_DRIFT         fill_value changes between levels
  COMPRESSOR_DRIFT   compressor/codec changes between levels
  SEPARATOR_DRIFT    dimension_separator changes between levels
  NDIM_DRIFT         levels disagree on dimensionality
  AXES_MISMATCH      declared axes count != array ndim
  CHUNK_EXCEEDS_SHAPE  chunk larger than the level itself on every axis
  DEGENERATE_LEVEL   a level has a zero/negative extent

Outputs (into --out-dir; existing files are backed up, never overwritten):
    audit_pyramid.levels.jsonl    one record per pyramid level
    audit_pyramid.pyramids.jsonl  one record per pyramid
    audit_pyramid.findings.csv    one row per finding (the reviewable artifact)
    audit_pyramid.summary.json    counts by code
    audit_pyramid.manifest.json   provenance

Usage:
    python bin/audit_pyramid.py --base https://dl.ash2txt.org/ \
        --roots tmp/discover_zarr.roots.jsonl
    python bin/audit_pyramid.py --base https://dl.ash2txt.org/ --root <path>
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zpa.httpstore import open_store                        # noqa: E402
from zpa.pool import parallel_map                           # noqa: E402
from zpa.runio import CsvWriter, JsonlWriter, RunManifest, write_json  # noqa: E402
from zpa.zarrmeta import read_pyramid                       # noqa: E402

SEVERITY = {
    "MULTISCALE_EMPTY": "high",
    "LEVEL_MISSING": "high",
    "LEVEL_NO_CHUNKS": "high",
    "SEPARATOR_DRIFT": "high",
    "DTYPE_DRIFT": "high",
    "SCALE_SHAPE_MISMATCH": "high",
    "DEGENERATE_LEVEL": "high",
    "NDIM_DRIFT": "high",
    "LEVEL_UNDECLARED": "medium",
    "SCALE_NONMONOTONIC": "medium",
    "FILL_DRIFT": "medium",
    "MIXED_ROUNDING": "medium",
    "COMPRESSOR_DRIFT": "low",
    "AXES_MISMATCH": "low",
    "HEADERLESS_CHUNK_STORE": "high",
    "CONTAINER_NO_GROUP_HEADER": "low",
    "EMPTY_ZARR_DIR": "low",
}

# Codes that describe what a node IS, not that anything is wrong. They are
# emitted so a run accounts for every root it was handed, but they must not
# be mixed into defect counts.
# CHUNK_EXCEEDS_SHAPE is informational: corpus-wide triage (78/78 findings) showed
# it only ever occurs on the deepest levels, where a fixed chunk shape carried
# down the pyramid inevitably exceeds the array. It is the natural consequence
# of constant chunking, not a defect.
INFO_CODES = {"NOT_A_ZARR_GROUP", "NOT_MULTISCALE", "BARE_ARRAY", "CHUNK_EXCEEDS_SHAPE"}
for _c in INFO_CODES:
    SEVERITY[_c] = "info"

FINDING_HEADER = ["code", "severity", "root", "level", "detail",
                  "observed", "expected"]


def _ratio(a: float, b: float) -> float | None:
    return (a / b) if b else None


def audit_one(pm) -> tuple[list[dict], list[dict], dict]:
    """Return (findings, level_records, pyramid_record) for one pyramid."""
    findings: list[dict] = []
    root = pm.root

    def add(code: str, level, detail: str, observed="", expected=""):
        findings.append({
            "code": code, "severity": SEVERITY.get(code, "medium"),
            "root": root, "level": "" if level is None else str(level),
            "detail": detail, "observed": str(observed), "expected": str(expected),
        })

    if not pm.has_multiscales:
        # Three genuinely different situations, previously conflated as one
        # high-severity finding. Only the third is a defect.
        if not pm.is_group:
            # Neither .zgroup nor zarr.json. Typically a plain directory whose
            # name ends in .zarr acting as a container for sibling arrays.
            # Nothing is corrupt, but any consumer globbing *.zarr and calling
            # zarr.open() on the result will fail here.
            nk = getattr(pm, "node_kind", "unknown")
            code = {
                "array": "BARE_ARRAY",
                "headerless_chunks": "HEADERLESS_CHUNK_STORE",
                "container": "CONTAINER_NO_GROUP_HEADER",
                "empty": "EMPTY_ZARR_DIR",
            }.get(nk, "NOT_A_ZARR_GROUP")
            add(code, None,
                getattr(pm, "node_detail", "") or "; ".join(pm.errors)
                or "no .zgroup and no zarr.json")
            kind = nk if nk != "unknown" else "not_a_zarr_group"
        elif not pm.multiscales_key_present:
            # A valid Zarr group that never claimed to be an OME pyramid --
            # e.g. a structure-tensor group holding named component arrays.
            # Out of scope for a pyramid audit; not a defect.
            keys = sorted(k for k in pm.attrs_raw.keys())[:8]
            add("NOT_MULTISCALE", None,
                f"valid zarr group, no multiscales key; attrs={keys}")
            kind = "not_multiscale"
        else:
            # Declares multiscales but the datasets list is missing, empty or
            # unparseable. Consumers WILL open this expecting a pyramid.
            add("MULTISCALE_EMPTY", None,
                "multiscales key present but datasets list empty/unparseable")
            kind = "multiscale_empty"
        return findings, [], {
            "root": root, "zarr_format": pm.zarr_format, "n_levels": 0,
            "is_group": pm.is_group, "kind": kind,
            "has_multiscales": False,
            "multiscales_key_present": pm.multiscales_key_present,
            "errors": pm.errors, "n_findings": len(findings),
        }

    levels = pm.levels
    present = [l for l in levels if l.present and l.shape]

    for l in levels:
        if not l.present:
            add("LEVEL_MISSING", l.path,
                f"declared in multiscales but no readable array header: {l.error}")
        elif l.shape and any(int(s) <= 0 for s in l.shape):
            add("DEGENERATE_LEVEL", l.path, "non-positive extent", l.shape)
        if l.present and l.has_chunks is False:
            # Header is valid, listing is trustworthy (it shows the header),
            # and there is not a single chunk key. Distinct from LEVEL_MISSING:
            # zarr.open() succeeds and silently serves fill_value everywhere.
            add("LEVEL_NO_CHUNKS", l.path,
                "array header present but level directory holds no chunk keys; "
                "reads return fill_value with no error",
                f"top_entries=0 fill_value={l.fill_value!r}",
                f"<={l.top_entries_max} top-level keys "
                f"({l.n_chunks} chunks if dense)")

    for extra in pm.extra_level_dirs:
        add("LEVEL_UNDECLARED", extra,
            "level directory readable on disk but absent from multiscales")

    if not present:
        return findings, [], {
            "root": root, "zarr_format": pm.zarr_format, "n_levels": len(levels),
            "has_multiscales": True, "errors": pm.errors, "n_findings": len(findings),
        }

    base = present[0]
    ndims = {len(l.shape) for l in present if l.shape}
    if len(ndims) > 1:
        add("NDIM_DRIFT", None, "levels disagree on ndim", sorted(ndims))
    if pm.axes and base.shape and len(pm.axes) != len(base.shape):
        add("AXES_MISMATCH", base.path,
            "declared axes count != array ndim", len(pm.axes), len(base.shape))

    # ---- attribute drift across levels ------------------------------------
    def drift(attr_fn, code, label):
        vals = {}
        for l in present:
            vals.setdefault(str(attr_fn(l)), []).append(l.path)
        if len(vals) > 1:
            add(code, None, f"{label} differs across levels",
                json.dumps(vals, sort_keys=True))

    drift(lambda l: l.dtype, "DTYPE_DRIFT", "dtype")
    drift(lambda l: l.fill_value, "FILL_DRIFT", "fill_value")
    drift(lambda l: l.compressor_id(), "COMPRESSOR_DRIFT", "compressor")
    drift(lambda l: l.dimension_separator, "SEPARATOR_DRIFT", "dimension_separator")

    # ---- declared scale monotonicity --------------------------------------
    scales = [l.declared_scale for l in present]
    for i in range(1, len(present)):
        s0, s1 = scales[i - 1], scales[i]
        if not s0 or not s1:
            continue
        if not all(b >= a for a, b in zip(s0, s1)) or s0 == s1:
            add("SCALE_NONMONOTONIC", present[i].path,
                "declared scale does not increase vs previous level",
                f"L{present[i-1].path}={s0} -> L{present[i].path}={s1}")

    # ---- shape vs declared scale (the core check) -------------------------
    roundings: set[str] = set()
    base_scale = base.declared_scale or [1.0] * len(base.shape)
    for l in present[1:]:
        if not l.shape or not l.declared_scale or not base.shape:
            continue
        if len(l.shape) != len(base.shape):
            continue
        factor = [_ratio(a, b) for a, b in zip(l.declared_scale, base_scale)]
        if any(f is None or f <= 0 for f in factor):
            continue
        exp_ceil = [max(1, math.ceil(s / f)) for s, f in zip(base.shape, factor)]
        exp_floor = [max(1, math.floor(s / f)) for s, f in zip(base.shape, factor)]
        got = list(l.shape)
        if got == exp_ceil and got == exp_floor:
            roundings.add("exact")
        elif got == exp_ceil:
            roundings.add("ceil")
        elif got == exp_floor:
            roundings.add("floor")
        else:
            add("SCALE_SHAPE_MISMATCH", l.path,
                f"shape matches neither ceil nor floor of base/{factor}",
                got, f"ceil={exp_ceil} floor={exp_floor}")

    concrete = roundings - {"exact"}
    if len(concrete) > 1:
        add("MIXED_ROUNDING", None,
            "pyramid mixes rounding conventions between levels",
            sorted(roundings))

    # ---- chunk sanity ------------------------------------------------------
    for l in present:
        if l.shape and l.chunks and len(l.shape) == len(l.chunks):
            if all(c >= s for c, s in zip(l.chunks, l.shape)) and l.n_voxels and l.n_voxels > 1:
                waste = 1.0
                for c, s in zip(l.chunks, l.shape):
                    waste *= (c / s) if s else 1
                if waste >= 8:
                    add("CHUNK_EXCEEDS_SHAPE", l.path,
                        f"chunk exceeds level extent on every axis (~{waste:.0f}x)",
                        f"chunks={l.chunks} shape={l.shape}")

    # ---- records -----------------------------------------------------------
    level_recs = [{
        "root": root, "level": l.path, "index": l.index, "present": l.present,
        "declared_scale": l.declared_scale, "shape": l.shape, "chunks": l.chunks,
        "dtype": l.dtype, "fill_value": l.fill_value,
        "compressor": l.compressor_id(),
        "dimension_separator": l.dimension_separator,
        "n_chunks": l.n_chunks, "n_voxels": l.n_voxels, "error": l.error,
        "has_chunks": l.has_chunks, "top_entries": l.top_entries,
        "top_entries_max": l.top_entries_max,
    } for l in levels]

    pyr_rec = {
        "root": root, "zarr_format": pm.zarr_format, "axes": pm.axes,
        "n_levels": len(levels), "n_levels_present": len(present),
        "has_multiscales": True,
        "base_shape": base.shape, "base_dtype": base.dtype,
        "rounding": sorted(roundings),
        "undeclared_levels": pm.extra_level_dirs,
        "levels_no_chunks": [l.path for l in present if l.has_chunks is False],
        "levels_chunks_unknown": [l.path for l in present if l.has_chunks is None],
        "errors": pm.errors,
        "n_findings": len(findings),
        "codes": sorted({f["code"] for f in findings}),
    }
    return findings, level_recs, pyr_rec


def load_roots(args) -> list[str]:
    roots: list[str] = []
    if args.root:
        roots.extend(args.root)
    if args.roots:
        with open(args.roots, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    roots.append(json.loads(line)["root"])
                except Exception:
                    continue
    # de-duplicate, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--roots", help="JSONL from discover_zarr.py")
    ap.add_argument("--root", action="append", help="explicit root (repeatable)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--max-rps", type=float, default=None)
    ap.add_argument("--probe-extra-levels", type=int, default=3)
    ap.add_argument("--no-chunk-presence", action="store_true",
                    help="skip the one-listing-per-level LEVEL_NO_CHUNKS probe")
    ap.add_argument("--max-flat-keys", type=int, default=250_000,
                    help="skip the chunk-presence listing for '.'-separated "
                         "levels with more chunks than this (autoindex size guard)")
    ap.add_argument("--limit", type=int, default=None,
                    help="audit only the first N roots (for a smoke test)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp")
    os.makedirs(out_dir, exist_ok=True)

    roots = load_roots(args)
    if args.limit:
        roots = roots[: args.limit]
    if not roots:
        print("no roots given: use --roots <jsonl> or --root <path>", file=sys.stderr)
        return 2

    store = open_store(args.base, timeout=args.timeout, max_rps=args.max_rps)

    lv_path = os.path.join(out_dir, "audit_pyramid.levels.jsonl")
    py_path = os.path.join(out_dir, "audit_pyramid.pyramids.jsonl")
    fd_path = os.path.join(out_dir, "audit_pyramid.findings.csv")
    sm_path = os.path.join(out_dir, "audit_pyramid.summary.json")

    codes = Counter()
    sev = Counter()
    n_pyr = 0
    n_bad_real = 0
    n_bad = 0

    with RunManifest("audit_pyramid", out_dir) as man, \
         JsonlWriter(lv_path) as w_lv, JsonlWriter(py_path) as w_py, \
         CsvWriter(fd_path, FINDING_HEADER) as w_fd:

        man.set("base", args.base)
        man.set("n_roots", len(roots))
        man.set("chunk_presence_check", not args.no_chunk_presence)
        man.set("max_flat_keys", args.max_flat_keys)

        def work(root: str):
            pm = read_pyramid(store, root,
                              probe_extra_levels=args.probe_extra_levels,
                              check_chunks=not args.no_chunk_presence,
                              max_flat_keys=args.max_flat_keys)
            return audit_one(pm)

        for res in parallel_map(work, roots, workers=args.workers,
                                label="auditing"):
            if not res.ok:
                man.count("audit_errors")
                w_fd.write({"code": "AUDIT_ERROR", "severity": "high",
                            "root": res.item, "level": "",
                            "detail": res.error, "observed": "", "expected": ""})
                codes["AUDIT_ERROR"] += 1
                sev["high"] += 1
                continue
            findings, level_recs, pyr_rec = res.value
            n_pyr += 1
            if any(f["code"] not in INFO_CODES for f in findings):
                n_bad_real += 1
            for r in level_recs:
                w_lv.write(r)
            w_py.write(pyr_rec)
            if findings:
                n_bad += 1
            for f in findings:
                w_fd.write(f)
                codes[f["code"]] += 1
                sev[f["severity"]] += 1

        summary = {
            "base": args.base,
            "roots_requested": len(roots),
            "pyramids_audited": n_pyr,
            "pyramids_with_findings": n_bad,
            "pyramids_clean": n_pyr - n_bad,
            "findings_total": int(sum(codes.values())),
            "findings_actionable": int(sum(v for k, v in codes.items()
                                           if k not in INFO_CODES)),
            "findings_informational": int(sum(v for k, v in codes.items()
                                              if k in INFO_CODES)),
            "pyramids_with_defects": n_bad_real,
            "by_code": dict(codes.most_common()),
            "by_severity": dict(sev.most_common()),
        }
        write_json(sm_path, summary)
        man.set("summary", summary)
        for p, d in ((lv_path, "per-level records"), (py_path, "per-pyramid records"),
                     (fd_path, "findings"), (sm_path, "summary")):
            man.add_output(p, d)

        print("\n=== SUMMARY ===")
        print(json.dumps(summary, indent=2))
        print(f"\nfindings -> {fd_path}")
        print(f"summary  -> {sm_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
