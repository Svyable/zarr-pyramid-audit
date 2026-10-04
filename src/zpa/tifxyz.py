#!/usr/bin/env python3
"""
tifxyz.py -- integrity audit for tifxyz surface patches (zpa-tifxyz).

A tifxyz surface is a directory holding ``meta.json`` plus three single-
channel TIFFs, ``x.tif``, ``y.tif`` and ``z.tif``: a 2-D grid whose cells
hold the 3-D voxel coordinates of a segmented papyrus surface. Invalid grid
points carry -1. ``meta.json`` declares ``format: "tifxyz"``, the grid
``scale`` and the ``bbox`` [[xmin,ymin,zmin],[xmax,ymax,zmax]] of the valid
points.

The same question as the pyramid audit, for surfaces: *is the data what its
metadata says it is?*

  header tier (default, a few hundred bytes per channel): meta.json is
      present and readable; the three channels exist, are valid TIFFs and
      share one grid; the samples are floating point.
  content tier (--content, reads the three channels in full): the surface
      has valid points at all; the channels agree on which points are
      invalid; valid coordinates are finite and non-negative (inside some
      volume); the declared bbox matches the coordinates actually stored.

Evidence semantics match the rest of the package: a confirmed 404 is
ABSENT, a read that fails (timeout, 403, 5xx, short range) is UNKNOWN and
never becomes a finding about the data. TIFF headers are parsed directly
(classic and BigTIFF, either byte order) with strict range reads, so a file
that imaging libraries refuse can still be reported. Content decoding covers
uncompressed and Deflate strips without a predictor; anything else is
decoded by `tifffile` + `imagecodecs` when installed
(`pip install 'zarr-pyramid-audit[tifxyz]'`), which covers the tiled,
LZW, BigTIFF and predictor-2/3 layouts found in the public bucket. Without
them, plain uncompressed and Deflate strips are decoded built-in and any
other layout is reported as a coverage gap (TIFXYZ_CONTENT_UNDECODED),
never guessed. Each report records which decoder produced its content
evidence.

Severities start at medium or below. Promoting any code to high needs
corpus-wide evidence (AGENTS.md lesson 5); see
artifacts/2026-10-01-s3-tifxyz/ for the first survey.

Outputs (into --out-dir; existing files are backed up, never overwritten):
    tifxyz.findings.csv     one row per finding
    tifxyz.reports.jsonl    one schema-versioned report per surface
    tifxyz.summary.json     counts
    tifxyz.manifest.json    provenance

Usage:
    zpa-tifxyz --base s3://vesuvius-challenge-open-data/ \\
        --roots tmp/discover_zarr.surfaces.jsonl --content --out-dir tmp/tifxyz
    zpa-tifxyz --base ./staging --root seg.tifxyz
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import zlib
from collections import Counter

import numpy as np

from zpa.httpstore import StoreError, _error_evidence, open_store
from zpa.pool import parallel_map
from zpa.report import SCHEMA_VERSION, TOOL, _max_severity, _tool_version, integrity_of
from zpa.runio import CsvWriter, JsonlWriter, RunManifest, write_json

CHANNELS = ("x", "y", "z")
INVALID = -1.0

TIFXYZ_SEVERITY = {
    "TIFXYZ_ABSENT": "low",                   # nothing there: no meta, no channels
    "TIFXYZ_META_MISSING": "medium",          # meta.json confirmed absent
    "TIFXYZ_META_UNREADABLE": "medium",       # meta.json present, not JSON object
    "TIFXYZ_META_INCOMPLETE": "low",          # format/scale/bbox missing or malformed
    "TIFXYZ_CHANNEL_MISSING": "medium",       # x/y/z.tif confirmed absent
    "TIFXYZ_TIFF_UNREADABLE": "medium",       # not a parseable TIFF
    "TIFXYZ_CHANNEL_SHAPE_MISMATCH": "medium",  # channels disagree on the grid
    "TIFXYZ_SAMPLE_FORMAT": "low",            # samples are not floating point
    "TIFXYZ_EMPTY": "medium",                 # content: no valid point at all
    "TIFXYZ_INVALID_MASK_MISMATCH": "low",    # content: channels disagree on -1
    "TIFXYZ_NONFINITE": "low",                # content: NaN/inf at valid points
    "TIFXYZ_NEGATIVE_COORDINATE": "low",      # content: valid point outside any volume
    "TIFXYZ_BBOX_MISMATCH": "low",            # content: meta bbox != data extent
    "TIFXYZ_TARGET_VOLUME_OVERRUN": "low",     # content: point >= exact CT upper bound
    "TIFXYZ_CONTENT_UNDECODED": "info",       # content tier skipped: coverage gap
    "ACCESS_UNKNOWN": "info",                 # a read could not be completed
}
INFO_CODES = {c for c, s in TIFXYZ_SEVERITY.items() if s == "info"}

FINDING_HEADER = ["code", "severity", "root", "level", "detail",
                  "observed", "expected", "evidence_state"]

# TIFF tag ids used here
_W, _H, _BITS, _COMP, _SPP, _SOFF, _SCNT, _SFMT, _PRED = (
    256, 257, 258, 259, 277, 273, 279, 339, 317)
_TILE_W = 322
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
              11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f",
             12: "d", 16: "Q", 17: "q", 18: "Q"}
_SAMPLE_FORMATS = {1: "uint", 2: "int", 3: "float"}


class TiffError(ValueError):
    """The bytes are present but are not a TIFF this parser understands."""


def _read(store, path: str, start: int, length: int) -> bytes:
    return store.get_range(path, start, length)


def parse_tiff_header(store, path: str, size: int) -> dict:
    """Parse the first IFD of a TIFF with strict range reads.

    Returns a dict with width, height, bits, compression, samples, sample
    format, tiling, predictor and the strip offsets/byte counts. Raises
    TiffError for malformed bytes and StoreError for failed reads.
    """
    if size < 8:
        raise TiffError(f"{size} bytes is too small for a TIFF header")
    head = _read(store, path, 0, min(16, size))
    order = head[:2]
    if order not in (b"II", b"MM"):
        raise TiffError(f"bad byte-order mark {order!r}")
    e = "<" if order == b"II" else ">"
    magic = struct.unpack(e + "H", head[2:4])[0]
    if magic == 42:
        big, off = False, struct.unpack(e + "I", head[4:8])[0]
        count_fmt, count_len, entry_len, inline = "H", 2, 12, 4
    elif magic == 43 and len(head) >= 16:
        big, off = True, struct.unpack(e + "Q", head[8:16])[0]
        count_fmt, count_len, entry_len, inline = "Q", 8, 20, 8
    else:
        raise TiffError(f"bad magic {magic}")
    if off < 8 or off + count_len > size:
        raise TiffError(f"first IFD offset {off} outside the {size}-byte file")
    n = struct.unpack(e + count_fmt, _read(store, path, off, count_len))[0]
    if n == 0 or off + count_len + n * entry_len > size:
        raise TiffError(f"IFD with {n} entries does not fit the file")
    raw = _read(store, path, off + count_len, n * entry_len)

    tags: dict[int, tuple] = {}
    for i in range(n):
        ent = raw[i * entry_len:(i + 1) * entry_len]
        if big:
            tag, typ, cnt = struct.unpack(e + "HHQ", ent[:12])
            val = ent[12:20]
        else:
            tag, typ, cnt = struct.unpack(e + "HHI", ent[:8])
            val = ent[8:12]
        if typ not in _TYPE_FMT or tag not in (
                _W, _H, _BITS, _COMP, _SPP, _SOFF, _SCNT, _SFMT, _PRED, _TILE_W):
            continue
        nbytes = _TYPE_SIZE[typ] * cnt
        if nbytes <= inline:
            data = val[:nbytes]
        else:
            ptr = struct.unpack(e + ("Q" if big else "I"), val[:inline])[0]
            if ptr + nbytes > size:
                raise TiffError(f"tag {tag} values outside the file")
            data = _read(store, path, ptr, nbytes)
        tags[tag] = struct.unpack(e + _TYPE_FMT[typ] * cnt, data)

    def one(tag, default=None):
        v = tags.get(tag)
        return v[0] if v else default

    if _W not in tags or _H not in tags:
        raise TiffError("missing ImageWidth/ImageLength")
    return {
        "width": int(one(_W)), "height": int(one(_H)),
        "bits": int(one(_BITS, 1)), "compression": int(one(_COMP, 1)),
        "samples_per_pixel": int(one(_SPP, 1)),
        "sample_format": _SAMPLE_FORMATS.get(int(one(_SFMT, 1)), "unknown"),
        "predictor": int(one(_PRED, 1)), "tiled": _TILE_W in tags,
        "byte_order": e, "bigtiff": big,
        "strip_offsets": list(tags.get(_SOFF, ())),
        "strip_byte_counts": list(tags.get(_SCNT, ())),
    }


def decode_channel(blob: bytes, hdr: dict) -> np.ndarray | None:
    """Decode a single-sample float channel; None if this layout is unsupported."""
    if (hdr["tiled"] or hdr["samples_per_pixel"] != 1
            or hdr["sample_format"] != "float" or hdr["bits"] not in (32, 64)
            or hdr["predictor"] != 1
            or hdr["compression"] not in (1, 8, 32946)
            or not hdr["strip_offsets"]
            or len(hdr["strip_offsets"]) != len(hdr["strip_byte_counts"])):
        return None
    parts = []
    for off, cnt in zip(hdr["strip_offsets"], hdr["strip_byte_counts"]):
        piece = blob[off:off + cnt]
        if len(piece) != cnt:
            return None
        if hdr["compression"] != 1:
            try:
                piece = zlib.decompress(piece)
            except zlib.error:
                return None
        parts.append(piece)
    dtype = np.dtype(f"{hdr['byte_order']}f{hdr['bits'] // 8}")
    data = b"".join(parts)
    want = hdr["width"] * hdr["height"] * dtype.itemsize
    if len(data) < want:
        return None
    return np.frombuffer(data[:want], dtype=dtype).reshape(
        hdr["height"], hdr["width"])


def _tifffile_decode(blob: bytes) -> np.ndarray | None:
    """Reference decoder for any layout tifffile/imagecodecs understand."""
    try:
        import io

        import tifffile
    except ImportError:
        return None
    try:
        arr = tifffile.imread(io.BytesIO(blob))
    except Exception:  # noqa: BLE001 -- undecodable is reported, not raised
        return None
    return arr if arr.ndim == 2 else None


def decoder_name() -> str:
    try:
        import tifffile
        return f"tifffile {tifffile.__version__}"
    except ImportError:
        return "builtin"


def decode_any(blob: bytes, hdr: dict) -> tuple[np.ndarray | None, str]:
    """Built-in path for plain strips, tifffile for everything else."""
    arr = decode_channel(blob, hdr)
    if arr is not None:
        return arr, "builtin"
    arr = _tifffile_decode(blob)
    if arr is not None:
        return arr, "tifffile"
    return None, ""


def _bbox_of(meta: dict):
    bbox = meta.get("bbox")
    try:
        lo, hi = [[float(v) for v in corner] for corner in bbox]
    except (TypeError, ValueError):
        return None
    if len(lo) != 3 or len(hi) != 3:
        return None
    return lo, hi


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-2)


def _canonical_volume_id(value) -> str | None:
    """Return a stable volume identifier from an ID, path or *.zarr name."""
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.strip().rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".zarr"):
        name = name[:-5]
    return name or None


def _normalize_target_shape_zyx(value) -> tuple[int, int, int] | None:
    """Validate an exact level-0 CT shape supplied for upper-bound checks."""
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in value)
    ):
        raise ValueError("target shape must be three positive integers: Z Y X")
    return tuple(int(v) for v in value)


def validate_expected_target_volume(store, roots: list[str], expected: str) -> None:
    """Fail closed unless every surface declares the exact expected CT target.

    This is an input guard, not a surface-quality finding. It is deliberately
    opt-in so legacy TIFXYZ directories without modern VC3D target metadata
    remain auditable under the existing evidence contract.
    """
    expected_id = _canonical_volume_id(expected)
    if expected_id is None:
        raise ValueError("expected target volume must be a non-empty volume ID or path")

    failures: list[str] = []
    for root in roots:
        clean_root = root.rstrip("/")
        evidence = store.json_evidence(f"{clean_root}/meta.json")
        if evidence.state != "PRESENT":
            failures.append(
                f"{clean_root}: meta.json target evidence is {evidence.state}"
            )
            continue
        if not isinstance(evidence.value, dict):
            failures.append(f"{clean_root}: meta.json is not a JSON object")
            continue
        declared = evidence.value.get("target_volume")
        observed_id = _canonical_volume_id(declared)
        if observed_id != expected_id:
            failures.append(
                f"{clean_root}: target_volume={declared!r} "
                f"(expected {expected_id!r})"
            )

    if failures:
        detail = "; ".join(failures[:8])
        if len(failures) > 8:
            detail += f"; ... and {len(failures) - 8} more"
        raise ValueError(
            "expected target-volume guard failed before audit: " + detail
        )


def audit_surface(store, root: str, *, content: bool = False,
                  max_content_bytes: int = 256 * 1024 * 1024,
                  target_shape_zyx: tuple[int, int, int] | list[int] | None = None) -> dict:
    """Audit one tifxyz surface; return its schema-versioned report."""
    root = root.rstrip("/")
    target_shape_zyx = _normalize_target_shape_zyx(target_shape_zyx)
    findings: list[dict] = []

    def add(code, level, detail, evidence="PRESENT", observed="", expected=""):
        findings.append({
            "code": code, "severity": TIFXYZ_SEVERITY[code], "level": level,
            "detail": detail, "observed": str(observed),
            "expected": str(expected), "evidence_state": evidence,
            "actionable": code not in INFO_CODES,
        })

    surface: dict = {"meta": None, "grid": None, "channels": {},
                     "valid_fraction": None, "data_bbox": None,
                     "content_checked": False}

    # ---- meta.json -----------------------------------------------------
    meta = None
    m = store.json_evidence(f"{root}/meta.json")
    if m.state == "UNKNOWN":
        add("ACCESS_UNKNOWN", "meta.json", f"meta.json could not be read: {m.error}",
            "UNKNOWN", m.reason)
    elif m.state == "ABSENT":
        add("TIFXYZ_META_MISSING", "meta.json", "meta.json is confirmed absent",
            "ABSENT")
    elif not isinstance(m.value, dict):
        add("TIFXYZ_META_UNREADABLE", "meta.json",
            f"meta.json is not a JSON object: {m.error or type(m.value).__name__}")
    else:
        meta = m.value
        surface["meta"] = {k: meta.get(k) for k in ("format", "type", "uuid",
                                                    "scale", "bbox")}
        # Modern VC3D writers record enough context to catch a surface copied
        # from the wrong scroll/volume. Preserve that evidence verbatim when
        # present; do not infer it for older TIFXYZ directories.
        for key in ("source", "target_volume", "scroll_source",
                    "vc_gsfs_mode", "vc_gsfs_version"):
            if key in meta:
                surface["meta"][key] = meta[key]
        problems = []
        if meta.get("format") != "tifxyz":
            problems.append(f"format={meta.get('format')!r}")
        scale = meta.get("scale")
        if not (isinstance(scale, list) and len(scale) == 2 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and v > 0 for v in scale)):
            problems.append(f"scale={scale!r}")
        if _bbox_of(meta) is None:
            problems.append("bbox is not [[x,y,z],[x,y,z]]")
        if problems:
            add("TIFXYZ_META_INCOMPLETE", "meta.json",
                "meta.json fields missing or malformed: " + "; ".join(problems),
                observed="; ".join(problems),
                expected="format='tifxyz', scale=[sx>0, sy>0], bbox=[[3],[3]]")

    # ---- channel headers -------------------------------------------------
    headers: dict[str, dict] = {}
    sizes: dict[str, int] = {}
    for ch in CHANNELS:
        path = f"{root}/{ch}.tif"
        level = f"{ch}.tif"
        info = store.head(path)
        if not getattr(info, "exists", False):
            if getattr(info, "status", None) == 404:
                surface["channels"][ch] = {"state": "ABSENT"}
                add("TIFXYZ_CHANNEL_MISSING", level, f"{level} is confirmed absent",
                    "ABSENT")
            else:
                state, reason = _error_evidence(str(info.error or info.status))
                surface["channels"][ch] = {"state": "UNKNOWN", "reason": reason}
                add("ACCESS_UNKNOWN", level,
                    f"{level} could not be checked: {info.error or info.status}",
                    "UNKNOWN", reason)
            continue
        size = info.size
        if not isinstance(size, int):
            surface["channels"][ch] = {"state": "UNKNOWN", "reason": "SIZE_UNKNOWN"}
            add("ACCESS_UNKNOWN", level, f"{level} size unknown", "UNKNOWN",
                "SIZE_UNKNOWN")
            continue
        try:
            hdr = parse_tiff_header(store, path, size)
        except TiffError as exc:
            surface["channels"][ch] = {"state": "PRESENT", "bytes": size,
                                       "tiff": False}
            add("TIFXYZ_TIFF_UNREADABLE", level, f"{level}: {exc}")
            continue
        except StoreError as exc:
            state, reason = _error_evidence(str(exc))
            surface["channels"][ch] = {"state": "UNKNOWN", "reason": reason}
            add("ACCESS_UNKNOWN", level, f"{level} header read failed: {exc}",
                "UNKNOWN", reason)
            continue
        headers[ch], sizes[ch] = hdr, size
        surface["channels"][ch] = {
            "state": "PRESENT", "bytes": size, "tiff": True,
            "width": hdr["width"], "height": hdr["height"], "bits": hdr["bits"],
            "sample_format": hdr["sample_format"],
            "compression": hdr["compression"], "tiled": hdr["tiled"]}
        if (hdr["sample_format"] != "float" or hdr["bits"] not in (32, 64)
                or hdr["samples_per_pixel"] != 1):
            add("TIFXYZ_SAMPLE_FORMAT", level,
                f"{level} holds {hdr['samples_per_pixel']} x "
                f"{hdr['sample_format']}{hdr['bits']} samples, not one float",
                observed=f"{hdr['sample_format']}{hdr['bits']} x{hdr['samples_per_pixel']}",
                expected="float32 x1")

    grids = {ch: (h["height"], h["width"]) for ch, h in headers.items()}
    if len(set(grids.values())) > 1:
        add("TIFXYZ_CHANNEL_SHAPE_MISMATCH", "",
            "channels disagree on the grid shape",
            observed=json.dumps({k: list(v) for k, v in sorted(grids.items())}),
            expected="one (height, width) for x, y and z")
    elif grids:
        surface["grid"] = list(next(iter(grids.values())))

    # ---- content tier ----------------------------------------------------
    can_read_content = (content and len(headers) == 3
                        and surface["grid"] is not None
                        and not any(f["code"] == "TIFXYZ_SAMPLE_FORMAT"
                                    for f in findings))
    if content and not can_read_content:
        # Content checks need three readable float channels on one grid;
        # the header findings above already say why that is not the case.
        surface["content_skipped"] = "header findings prevent content checks"
    if can_read_content:
        # Check every channel against the cap before downloading any of them.
        too_big = [ch for ch in CHANNELS if sizes[ch] > max_content_bytes]
        if too_big:
            ch = too_big[0]
            add("TIFXYZ_CONTENT_UNDECODED", f"{ch}.tif",
                f"{ch}.tif is {sizes[ch]} bytes, above --max-content-bytes")
            can_read_content = False
    if can_read_content:
        arrays: dict[str, np.ndarray] = {}
        for ch in CHANNELS:
            level = f"{ch}.tif"
            try:
                blob = store.get(f"{root}/{ch}.tif")
            except StoreError as exc:
                state, reason = _error_evidence(str(exc))
                add("ACCESS_UNKNOWN", level, f"{level} content read failed: {exc}",
                    "UNKNOWN", reason)
                break
            arr, how = decode_any(blob, headers[ch])
            if arr is None:
                h = headers[ch]
                hint = ("" if decoder_name() != "builtin" else
                        "; install zarr-pyramid-audit[tifxyz] for tifffile")
                add("TIFXYZ_CONTENT_UNDECODED", level,
                    f"{level} layout not decoded (compression="
                    f"{h['compression']}, predictor={h['predictor']}, "
                    f"tiled={h['tiled']}, {h['sample_format']}{h['bits']}){hint}")
                break
            if arr.shape != tuple(surface["grid"]):
                add("TIFXYZ_TIFF_UNREADABLE", level,
                    f"{level} decodes to {arr.shape}, header says "
                    f"{tuple(surface['grid'])}")
                break
            arrays[ch] = arr
            surface.setdefault("decoders", {})[ch] = how
        if len(arrays) == 3:
            _content_checks(arrays, meta, surface, add,
                            target_shape_zyx=target_shape_zyx)

    if (meta is None and not headers and findings
            and all(f["evidence_state"] == "ABSENT" for f in findings)):
        # Every probe confirmed absence: one "nothing to audit" finding
        # instead of four, and integrity UNKNOWN (never PASS).
        findings.clear()
        add("TIFXYZ_ABSENT", "",
            "surface is confirmed absent: no meta.json and no x/y/z.tif",
            "ABSENT")
        evidence = {"state": "ABSENT", "reason": "NOT_FOUND"}
    elif any(f["code"] == "ACCESS_UNKNOWN" for f in findings):
        evidence = {"state": "UNKNOWN", "reason": next(
            f["observed"] for f in findings if f["code"] == "ACCESS_UNKNOWN")}
    elif any(f["evidence_state"] == "ABSENT" for f in findings):
        evidence = {"state": "PRESENT", "reason": "PARTS_ABSENT"}
    else:
        evidence = {"state": "PRESENT", "reason": None}
    integrity = integrity_of(findings)
    return {
        "schema_version": SCHEMA_VERSION, "tool": TOOL,
        "tool_version": _tool_version(), "root": root, "kind": "tifxyz",
        "evidence": evidence, "integrity": integrity,
        "max_severity": _max_severity(findings),
        "tiers": {"header": True, "content": bool(content)},
        "surface": surface, "findings": findings,
    }


def _content_checks(arrays, meta, surface, add, *, target_shape_zyx=None) -> None:
    # Native dtype on purpose: -1 equality, finiteness and min/max are exact
    # in float32, and a float64 copy would triple peak memory per worker.
    x, y, z = (arrays[c] for c in CHANNELS)
    surface["content_checked"] = True
    marked = [(a == INVALID) for a in (x, y, z)]
    all_marked = marked[0] & marked[1] & marked[2]
    any_marked = marked[0] | marked[1] | marked[2]
    partial = int((any_marked & ~all_marked).sum())
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    valid = ~any_marked & finite
    n_total, n_valid = int(x.size), int(valid.sum())
    surface["valid_fraction"] = round(n_valid / n_total, 6) if n_total else 0.0
    nonfinite = int((~any_marked & ~finite).sum())

    if n_valid == 0:
        add("TIFXYZ_EMPTY", "",
            f"no valid point among {n_total} grid cells: every cell is -1 or "
            "non-finite, so the surface has no geometry",
            observed=f"0/{n_total} valid", expected=">0 valid points")
        return
    if partial:
        add("TIFXYZ_INVALID_MASK_MISMATCH", "",
            f"{partial} grid cells are -1 in some channels but not all",
            observed=partial, expected=0)
    if nonfinite:
        add("TIFXYZ_NONFINITE", "",
            f"{nonfinite} cells not marked -1 hold NaN or inf",
            observed=nonfinite, expected=0)
    # Voxel coordinates are >= 0 in every CT volume, so a valid point with a
    # negative coordinate lies outside the scan whatever the volume is.
    negative = valid & ((x < 0) | (y < 0) | (z < 0))
    n_negative = int(negative.sum())
    if n_negative:
        axes = [ax for ax, a in zip("xyz", (x, y, z)) if bool((valid & (a < 0)).any())]
        add("TIFXYZ_NEGATIVE_COORDINATE", "",
            f"{n_negative} of {n_valid} valid points have a negative "
            f"{'/'.join(axes)} coordinate: they lie outside any CT volume",
            observed=n_negative, expected=0)
    lo = [float(a[valid].min()) for a in (x, y, z)]
    hi = [float(a[valid].max()) for a in (x, y, z)]
    surface["data_bbox"] = [lo, hi]
    if target_shape_zyx is not None:
        z_size, y_size, x_size = target_shape_zyx
        upper = valid & ((x >= x_size) | (y >= y_size) | (z >= z_size))
        n_upper = int(upper.sum())
        surface["target_shape_zyx"] = [z_size, y_size, x_size]
        surface["target_overrun_points"] = n_upper
        if n_upper:
            axes = [
                axis
                for axis, arr, size in zip("xyz", (x, y, z), (x_size, y_size, z_size))
                if bool((valid & (arr >= size)).any())
            ]
            add(
                "TIFXYZ_TARGET_VOLUME_OVERRUN",
                "",
                f"{n_upper} of {n_valid} valid points reach or exceed the exact "
                f"target CT upper bound on {'/'.join(axes)}; valid voxel "
                "coordinates must be strictly below the corresponding shape",
                observed=n_upper,
                expected=0,
            )
    declared = _bbox_of(meta) if isinstance(meta, dict) else None
    if declared is not None:
        dlo, dhi = declared
        if not all(_close(a, b) for a, b in zip(lo + hi, dlo + dhi)):
            # Which way is it wrong? Stored points outside the declared box
            # mean a consumer cropping to the bbox loses real geometry; a
            # box that is merely too large is loose, not lossy.
            outside = np.zeros_like(valid)
            for arr, l_, h_ in zip((x, y, z), dlo, dhi):
                tol_l = max(1e-2, abs(l_) * 1e-5)
                tol_h = max(1e-2, abs(h_) * 1e-5)
                outside |= valid & ((arr < l_ - tol_l) | (arr > h_ + tol_h))
            n_out = int(outside.sum())
            sentinel_axes = [ax for ax, l_, d_ in zip("xyz", dlo, lo)
                             if l_ == INVALID and d_ > INVALID]
            parts = []
            if n_out:
                parts.append(f"{n_out} of {n_valid} valid points lie outside "
                             "the declared bbox (cropping to it would drop "
                             "geometry)")
            else:
                parts.append("the declared bbox is larger than the stored "
                             "coordinates (loose, nothing outside it)")
            if sentinel_axes:
                parts.append("declared minimum is -1 on "
                             + ",".join(sentinel_axes)
                             + ": the -1 invalid marker was likely included "
                             "when the bbox was computed")
            surface["bbox_points_outside"] = n_out
            add("TIFXYZ_BBOX_MISMATCH", "meta.json", "; ".join(parts),
                observed=json.dumps([[round(v, 3) for v in lo],
                                     [round(v, 3) for v in hi]]),
                expected=json.dumps([[round(v, 3) for v in dlo],
                                     [round(v, 3) for v in dhi]]))


def load_roots(args) -> list[str]:
    roots: list[str] = list(args.root or [])
    if args.roots:
        with open(args.roots, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    roots.append(json.loads(line)["root"])
    seen: set[str] = set()
    return [r for r in roots if not (r in seen or seen.add(r))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True,
                    help="store base: http(s)://, s3://, file:// or a local directory")
    ap.add_argument("--roots", help="JSONL with a 'root' per line "
                                    "(e.g. discover_zarr.surfaces.jsonl)")
    ap.add_argument("--root", action="append", help="explicit surface (repeatable)")
    ap.add_argument("--content", action="store_true",
                    help="also read x/y/z in full and check the coordinates")
    ap.add_argument(
        "--expected-target-volume",
        help=(
            "optional fail-closed compliance guard: require every surface "
            "meta.json target_volume to identify this exact CT volume before "
            "any audit outputs are written"
        ),
    )
    ap.add_argument(
        "--target-shape-zyx",
        nargs=3,
        type=int,
        metavar=("Z", "Y", "X"),
        help=(
            "optional exact level-0 CT shape for content-tier upper-bound "
            "checks; requires --expected-target-volume so the shape cannot "
            "silently be applied to the wrong CT"
        ),
    )
    ap.add_argument("--max-content-bytes", type=int, default=256 * 1024 * 1024)
    ap.add_argument("--fail-on", default=None,
                    choices=["high", "medium", "low", "info"],
                    help="exit 1 if any surface has a finding at or above this "
                         "severity, or integrity UNKNOWN (gate mode)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--max-rps", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-dir", default="tmp/tifxyz")
    args = ap.parse_args(argv)

    if args.target_shape_zyx and not args.expected_target_volume:
        print(
            "zpa-tifxyz: --target-shape-zyx requires --expected-target-volume",
            file=sys.stderr,
        )
        return 2
    try:
        target_shape_zyx = _normalize_target_shape_zyx(args.target_shape_zyx)
    except ValueError as exc:
        print(f"zpa-tifxyz: {exc}", file=sys.stderr)
        return 2

    roots = load_roots(args)
    if args.limit:
        roots = roots[:args.limit]
    if not roots:
        print("no roots given: use --roots <jsonl> or --root <path>", file=sys.stderr)
        return 2
    os.makedirs(args.out_dir, exist_ok=True)
    kw = {} if args.base.startswith("s3://") else {
        "timeout": args.timeout, "max_rps": args.max_rps}
    store = open_store(args.base, **kw)
    if args.expected_target_volume:
        try:
            validate_expected_target_volume(
                store, roots, args.expected_target_volume
            )
        except ValueError as exc:
            print(f"zpa-tifxyz: {exc}", file=sys.stderr)
            return 2

    fd_path = os.path.join(args.out_dir, "tifxyz.findings.csv")
    rp_path = os.path.join(args.out_dir, "tifxyz.reports.jsonl")
    sm_path = os.path.join(args.out_dir, "tifxyz.summary.json")
    codes, integ, sev = Counter(), Counter(), Counter()
    content_checked = 0
    failed = 0
    order = {"info": 0, "low": 1, "medium": 2, "high": 3}
    with RunManifest("tifxyz", args.out_dir) as man, \
         CsvWriter(fd_path, FINDING_HEADER) as w_fd, JsonlWriter(rp_path) as w_rp:
        man.set("base", args.base)
        man.set("n_roots", len(roots))
        man.set("content", bool(args.content))
        man.set("expected_target_volume", args.expected_target_volume)
        man.set("target_shape_zyx", list(target_shape_zyx) if target_shape_zyx else None)
        for res in parallel_map(
                lambda r: audit_surface(store, r, content=args.content,
                                        max_content_bytes=args.max_content_bytes,
                                        target_shape_zyx=target_shape_zyx),
                roots, workers=args.workers, label="tifxyz"):
            if not res.ok:
                rep = {"root": res.item, "integrity": "FAIL", "findings": [{
                    "code": "AUDIT_ERROR", "severity": "high", "level": "",
                    "detail": res.error, "observed": "", "expected": "",
                    "evidence_state": "UNKNOWN"}]}
                man.count("audit_errors")
            else:
                rep = res.value
                w_rp.write(rep)
                content_checked += bool(rep["surface"]["content_checked"])
            integ[rep["integrity"]] += 1
            for f in rep["findings"]:
                w_fd.write({"root": rep["root"], **{k: f.get(k, "") for k in
                            FINDING_HEADER if k != "root"}})
                codes[f["code"]] += 1
                sev[f["severity"]] += 1
            if args.fail_on and (rep["integrity"] == "UNKNOWN" or any(
                    order[f["severity"]] >= order[args.fail_on]
                    for f in rep["findings"])):
                failed += 1
        summary = {"base": args.base, "surfaces": len(roots),
                   "content_tier": bool(args.content),
                   "expected_target_volume": args.expected_target_volume,
                   "target_shape_zyx": (list(target_shape_zyx) if target_shape_zyx else None),
                   "content_checked": content_checked,
                   "by_integrity": dict(integ.most_common()),
                   "by_code": dict(codes.most_common()),
                   "by_severity": dict(sev.most_common())}
        if args.fail_on:
            summary["gate"] = {"fail_on": args.fail_on, "failed": failed}
        write_json(sm_path, summary)
        man.set("summary", summary)
        for p, d in ((fd_path, "findings"), (rp_path, "per-surface reports"),
                     (sm_path, "summary")):
            man.add_output(p, d)
    print(json.dumps(summary, indent=2))
    return 1 if (args.fail_on and failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
