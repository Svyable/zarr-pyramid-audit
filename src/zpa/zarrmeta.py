"""
zarrmeta.py -- read OME-Zarr / Zarr metadata from a remote store WITHOUT
opening the arrays.

Everything here is header-only: a whole multiscale pyramid is described from
a handful of small JSON objects (.zattrs + one .zarray per level), typically
a few kilobytes total, regardless of whether the array is 3 GB or 3 TB. That
is what makes a corpus-wide survey cheap and polite.

Supports zarr v2 (.zgroup/.zattrs/.zarray) and zarr v3 (zarr.json), and both
the OME-NGFF `multiscales` layouts seen in the wild.
"""

from __future__ import annotations

import math
import posixpath
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Sequence

__all__ = ["LevelMeta", "PyramidMeta", "read_pyramid", "chunk_key",
           "chunk_grid", "expected_shape"]


@dataclass
class LevelMeta:
    """One resolution level of a pyramid."""
    path: str                       # e.g. "0"
    index: int                      # position in the multiscales list
    declared_scale: list[float] | None = None   # OME coordinateTransformations
    shape: list[int] | None = None
    chunks: list[int] | None = None
    dtype: str | None = None
    fill_value: Any = None
    compressor: Any = None
    dimension_separator: str = "."
    zarr_format: int | None = None
    order: str | None = None
    dimension_names: list | None = None     # zarr v3 arrays only
    present: bool = False
    error: str | None = None
    evidence_state: str = "UNKNOWN"
    evidence_reason: str | None = None
    # Chunk presence, from ONE directory listing of the level's top directory.
    # None means "not checked" or "listing unreliable" -- absence of evidence
    # is never reported as absence of chunks.
    has_chunks: bool | None = None
    chunk_evidence_state: str = "UNKNOWN"
    chunk_evidence_reason: str | None = None
    top_entries: int | None = None       # non-metadata entries actually listed
    top_entries_max: int | None = None   # what a DENSE level would show

    @property
    def n_chunks(self) -> int | None:
        if not self.shape or not self.chunks:
            return None
        n = 1
        for s, c in zip(self.shape, self.chunks):
            if c <= 0:
                return None
            n *= max(1, math.ceil(s / c))
        return n

    @property
    def n_voxels(self) -> int | None:
        if not self.shape:
            return None
        n = 1
        for s in self.shape:
            n *= int(s)
        return n

    def compressor_id(self) -> str:
        c = self.compressor
        if c is None:
            return "none"
        if isinstance(c, dict):
            cid = c.get("id") or c.get("name") or "?"
            inner = c.get("cname") or (c.get("configuration", {}) or {}).get("cname")
            lvl = c.get("clevel")
            if lvl is None:
                lvl = (c.get("configuration", {}) or {}).get("clevel")
            bits = [str(cid)]
            if inner:
                bits.append(str(inner))
            if lvl is not None:
                bits.append(f"l{lvl}")
            return ":".join(bits)
        if isinstance(c, list):
            return ",".join(
                (x.get("name") or x.get("id") or "?") if isinstance(x, dict) else str(x)
                for x in c
            ) or "none"
        return str(c)


@dataclass
class PyramidMeta:
    """A multiscale group: its OME metadata plus every level's array header."""
    root: str
    zarr_format: int | None = None
    is_group: bool = False
    # What a non-group node actually is, so callers can tell a valid bare
    # array from a corrupt chunk store:
    #   group | array | headerless_chunks | container | absent | empty | not_zarr | unknown
    node_kind: str = "unknown"
    node_detail: str = ""
    evidence_state: str = "UNKNOWN"
    evidence_reason: str | None = None
    has_multiscales: bool = False        # datasets list is usable
    multiscales_key_present: bool = False  # key exists, may be empty
    axes: list[str] = field(default_factory=list)
    levels: list[LevelMeta] = field(default_factory=list)
    attrs_raw: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    extra_level_dirs: list[str] = field(default_factory=list)

    @property
    def n_levels(self) -> int:
        return len(self.levels)

    @property
    def base(self) -> LevelMeta | None:
        return self.levels[0] if self.levels else None


def _as_int_list(v: Any) -> list[int] | None:
    if not isinstance(v, (list, tuple)):
        return None
    try:
        return [int(x) for x in v]
    except (TypeError, ValueError):
        return None


def _as_float_list(v: Any) -> list[float] | None:
    if not isinstance(v, (list, tuple)):
        return None
    try:
        return [float(x) for x in v]
    except (TypeError, ValueError):
        return None


def _extract_multiscales(attrs: dict[str, Any]) -> tuple[list[dict], list[str]]:
    """Return (datasets, axis_names) from either OME-NGFF layout."""
    ms = attrs.get("multiscales")
    if ms is None:
        ome = attrs.get("ome")
        if isinstance(ome, dict):
            ms = ome.get("multiscales")
    if not isinstance(ms, list) or not ms:
        return [], []
    first = ms[0] if isinstance(ms[0], dict) else {}
    datasets = first.get("datasets") or []
    axes_raw = first.get("axes") or []
    axes: list[str] = []
    for a in axes_raw:
        if isinstance(a, dict):
            axes.append(str(a.get("name", "?")))
        else:
            axes.append(str(a))
    return ([d for d in datasets if isinstance(d, dict)], axes)


def _scale_of(dataset: dict[str, Any]) -> list[float] | None:
    for ct in dataset.get("coordinateTransformations") or []:
        if isinstance(ct, dict) and ct.get("type") == "scale":
            s = _as_float_list(ct.get("scale"))
            if s:
                return s
    return None


def _parse_v2_array(j: dict[str, Any]) -> dict[str, Any]:
    return dict(
        shape=_as_int_list(j.get("shape")),
        chunks=_as_int_list(j.get("chunks")),
        dtype=str(j.get("dtype")) if j.get("dtype") is not None else None,
        fill_value=j.get("fill_value"),
        compressor=j.get("compressor"),
        dimension_separator=str(j.get("dimension_separator") or "."),
        zarr_format=2,
        order=j.get("order"),
    )


def _parse_v3_array(j: dict[str, Any]) -> dict[str, Any]:
    chunks = None
    sep = "/"
    cg = j.get("chunk_grid") or {}
    if isinstance(cg, dict):
        chunks = _as_int_list((cg.get("configuration") or {}).get("chunk_shape"))
    ck = j.get("chunk_key_encoding") or {}
    if isinstance(ck, dict):
        sep = str((ck.get("configuration") or {}).get("separator") or "/")
    dt = j.get("data_type")
    codecs = j.get("codecs")
    return dict(
        shape=_as_int_list(j.get("shape")),
        chunks=chunks,
        dtype=str(dt) if dt is not None else None,
        fill_value=j.get("fill_value"),
        compressor=codecs,
        dimension_separator=sep,
        zarr_format=3,
        order=None,
        dimension_names=(list(j["dimension_names"])
                         if isinstance(j.get("dimension_names"), list) else None),
    )


_CHUNK_KEY_RE = re.compile(r"^\d+(\.\d+)*$")


def _json_evidence(store, path: str):
    """Use the evidence API when available without breaking legacy stores."""
    method = getattr(store, "json_evidence", None)
    if callable(method):
        return method(path)
    try:
        value, error = store.try_json(path)
    except Exception as exc:  # legacy adapters were allowed to raise
        error = f"{type(exc).__name__}: {exc}"
        return SimpleNamespace(value=None, state="UNKNOWN",
                               reason="LEGACY_ACCESS_ERROR", error=error)
    if value is not None:
        return SimpleNamespace(value=value, state="PRESENT", reason=None, error=None)
    text = str(error or "")
    low = text.lower()
    if text.startswith("404 Not Found") or "filenotfounderror" in low:
        state, reason = "ABSENT", "NOT_FOUND"
    elif ("jsondecodeerror" in low or "invalid json" in low
          or "expecting value" in low):
        state, reason = "PRESENT", "METADATA_UNREADABLE"
    else:
        state, reason = "UNKNOWN", "LEGACY_ACCESS_ERROR"
    return SimpleNamespace(value=None, state=state, reason=reason, error=error)


def _list_evidence(store, path: str):
    """Use evidence listings when available and preserve the old store API."""
    method = getattr(store, "list_dir_evidence", None)
    if callable(method):
        return method(path)
    try:
        dirs, files = store.list_dir(path)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return SimpleNamespace(dirs=[], files=[], state="UNKNOWN",
                               reason="LISTING_ERROR", error=error)
    return SimpleNamespace(dirs=list(dirs), files=list(files),
                           state="PRESENT", reason=None, error=None)


def _failed_json_evidence(*results) -> tuple[str, str | None]:
    """Combine failed alternative header probes without strengthening evidence."""
    unreadable = next((r for r in results
                       if r.state == "PRESENT" and r.reason == "METADATA_UNREADABLE"), None)
    if unreadable is not None:
        return "PRESENT", "METADATA_UNREADABLE"
    if results and all(r.state == "ABSENT" for r in results):
        return "ABSENT", "NOT_FOUND"
    unknown = next((r for r in results if r.state == "UNKNOWN"), None)
    if unknown is not None:
        return "UNKNOWN", unknown.reason
    return "UNKNOWN", "METADATA_UNREADABLE"


def _classify_non_group(store, root: str, pm: PyramidMeta,
                        prior_headers=()) -> None:
    """
    Classify a non-group root without turning failed access into absence.
    """
    za_result = _json_evidence(store, f"{root}/.zarray")
    za = za_result.value
    if isinstance(za, dict):
        pm.evidence_state = "PRESENT"
        pm.node_kind = "array"
        pm.node_detail = (f"bare zarr v2 array shape={za.get('shape')} "
                          f"chunks={za.get('chunks')} dtype={za.get('dtype')}")
        return

    header_state, header_reason = _failed_json_evidence(
        *tuple(prior_headers), za_result)
    if header_state == "PRESENT" and header_reason == "METADATA_UNREADABLE":
        pm.evidence_state = "PRESENT"
        pm.evidence_reason = "METADATA_UNREADABLE"
        pm.node_kind = "unknown"
        pm.node_detail = "Zarr metadata exists but is unreadable"
        return

    listed = _list_evidence(store, root)
    dirs, files = listed.dirs, listed.files
    if listed.state == "UNKNOWN":
        pm.evidence_state = "UNKNOWN"
        pm.evidence_reason = listed.reason
        pm.node_kind = "unknown"
        pm.node_detail = f"directory listing unavailable: {listed.error}"
        return
    if header_state == "UNKNOWN":
        pm.evidence_state = "UNKNOWN"
        pm.evidence_reason = header_reason
        pm.node_kind = "unknown"
        pm.node_detail = "one or more Zarr header probes were inconclusive"
        return
    if not dirs and not files:
        pm.evidence_state = "ABSENT"
        if listed.state == "PRESENT":
            pm.evidence_reason = "EMPTY_STRUCTURE"
            pm.node_kind = "empty"
            pm.node_detail = "directory listing succeeded and is empty"
        else:
            pm.evidence_reason = listed.reason or "NOT_FOUND"
            pm.node_kind = "absent"
            pm.node_detail = "metadata probes and root listing confirm absence"
        return

    chunk_keys = [f for f in files if _CHUNK_KEY_RE.match(f)]
    if chunk_keys and not any(f in (".zarray", ".zgroup", "zarr.json") for f in files):
        pm.evidence_state = "PRESENT"
        pm.node_kind = "headerless_chunks"
        pm.node_detail = (f"{len(chunk_keys)} chunk-like keys (e.g. {chunk_keys[0]}) "
                          f"but no .zarray/.zgroup/zarr.json -- undecodable")
        return

    zarr_children = 0
    unknown_child = None
    for d in dirs[:4]:
        for hdr in (".zgroup", ".zarray", "zarr.json"):
            result = _json_evidence(store, f"{root}/{d}/{hdr}")
            if isinstance(result.value, dict):
                zarr_children += 1
                break
            if result.state == "UNKNOWN" and unknown_child is None:
                unknown_child = result
    if zarr_children:
        pm.evidence_state = "PRESENT"
        pm.node_kind = "container"
        pm.node_detail = (f"{zarr_children}/{min(4, len(dirs))} probed children are Zarr "
                          f"nodes ({dirs[:4]}); no group header at root")
        return
    if unknown_child is not None:
        pm.evidence_state = "UNKNOWN"
        pm.evidence_reason = unknown_child.reason
        pm.node_kind = "unknown"
        pm.node_detail = "child Zarr probes were inconclusive"
        return

    pm.evidence_state = "PRESENT"
    pm.node_kind = "not_zarr"
    pm.node_detail = f"{len(dirs)} dirs, {len(files)} files, none Zarr-like"


_META_NAMES = frozenset({".zarray", ".zattrs", ".zgroup", ".zmetadata", "zarr.json"})


def _probe_chunk_presence(store, apath: str, lm: LevelMeta,
                          max_flat_keys: int) -> None:
    """
    Detect header-present levels with zero observable chunk keys.

    A negative finding requires a successful listing that also exposes the
    level header. Listing failures remain UNKNOWN and never become absence.
    """
    if lm.shape and lm.chunks and len(lm.shape) == len(lm.chunks):
        g = chunk_grid(lm.shape, lm.chunks)
        if lm.zarr_format == 3:
            lm.top_entries_max = 1
        elif lm.dimension_separator == "/":
            lm.top_entries_max = g[0] if g else None
        else:
            lm.top_entries_max = lm.n_chunks
        if (lm.dimension_separator != "/" and lm.zarr_format != 3
                and lm.n_chunks and lm.n_chunks > max_flat_keys):
            lm.chunk_evidence_reason = "LISTING_SKIPPED_SIZE_GUARD"
            return
    try:
        listed = _list_evidence(store, apath)
    except Exception as e:  # noqa: BLE001
        lm.chunk_evidence_state = "UNKNOWN"
        lm.chunk_evidence_reason = "LISTING_ERROR"
        lm.error = (lm.error + " | " if lm.error else "") + f"list_dir: {e}"
        return
    if listed.state != "PRESENT":
        lm.chunk_evidence_state = "UNKNOWN"
        lm.chunk_evidence_reason = listed.reason
        lm.error = (lm.error + " | " if lm.error else "") + f"list_dir: {listed.error}"
        return
    entries = list(listed.dirs) + list(listed.files)
    if not entries:
        lm.chunk_evidence_state = "UNKNOWN"
        lm.chunk_evidence_reason = "EMPTY_LISTING_UNVERIFIED"
        return
    chunk_entries = [n for n in entries if n not in _META_NAMES]
    lm.top_entries = len(chunk_entries)
    if chunk_entries:
        lm.has_chunks = True
        lm.chunk_evidence_state = "PRESENT"
        lm.chunk_evidence_reason = None
    elif any(n in (".zarray", "zarr.json") for n in entries):
        lm.has_chunks = False
        lm.chunk_evidence_state = "ABSENT"
        lm.chunk_evidence_reason = "NO_CHUNK_KEYS"
    else:
        lm.chunk_evidence_state = "UNKNOWN"
        lm.chunk_evidence_reason = "LISTING_INCOMPLETE"


def read_pyramid(store, root: str, *, probe_extra_levels: int = 3,
                 check_chunks: bool = True,
                 max_flat_keys: int = 250_000) -> PyramidMeta:
    """Read a pyramid's metadata while keeping access evidence explicit."""
    root = root.rstrip("/")
    pm = PyramidMeta(root=root)

    attrs: dict[str, Any] = {}
    zg_result = _json_evidence(store, f"{root}/.zgroup")
    zg, e_zg = zg_result.value, zg_result.error
    if isinstance(zg, dict):
        pm.evidence_state = "PRESENT"
        pm.is_group = True
        pm.node_kind = "group"
        pm.zarr_format = int(zg.get("zarr_format") or 2)
        za_result = _json_evidence(store, f"{root}/.zattrs")
        za, e_za = za_result.value, za_result.error
        if isinstance(za, dict):
            attrs = za
        elif e_za:
            pm.errors.append(f".zattrs unreadable: {e_za}")
            if za_result.state == "UNKNOWN":
                pm.evidence_state = "UNKNOWN"
                pm.evidence_reason = za_result.reason
            elif za_result.state == "PRESENT":
                pm.evidence_reason = za_result.reason
    else:
        z3_result = _json_evidence(store, f"{root}/zarr.json")
        z3, e_z3 = z3_result.value, z3_result.error
        if isinstance(z3, dict):
            pm.evidence_state = "PRESENT"
            pm.is_group = (z3.get("node_type") == "group")
            pm.zarr_format = int(z3.get("zarr_format") or 3)
            attrs = z3.get("attributes") or {}
            if not pm.is_group and z3.get("node_type") == "array":
                arr = _parse_v3_array(z3)
                pm.node_kind = "array"
                pm.node_detail = (f"bare zarr v3 array shape={arr.get('shape')} "
                                  f"chunks={arr.get('chunks')} "
                                  f"dtype={arr.get('dtype')}")
        else:
            pm.errors.append(f"no .zgroup ({e_zg}) and no zarr.json ({e_z3})")
            _classify_non_group(store, root, pm, (zg_result, z3_result))
            return pm

    pm.attrs_raw = attrs
    datasets, axes = _extract_multiscales(attrs)
    pm.axes = axes
    pm.has_multiscales = bool(datasets)
    _ome = attrs.get("ome")
    pm.multiscales_key_present = bool(
        "multiscales" in attrs
        or (isinstance(_ome, dict) and "multiscales" in _ome)
    )

    if not datasets:
        pm.errors.append("group has no multiscales/datasets")
        return pm

    declared_paths: set[str] = set()
    for i, ds in enumerate(datasets):
        p = str(ds.get("path", i))
        declared_paths.add(p)
        lm = LevelMeta(path=p, index=i, declared_scale=_scale_of(ds))
        apath = posixpath.join(root, p)
        j_result = _json_evidence(store, f"{apath}/.zarray")
        j, err = j_result.value, j_result.error
        if isinstance(j, dict):
            for k, v in _parse_v2_array(j).items():
                setattr(lm, k, v)
            lm.present = True
            lm.evidence_state = "PRESENT"
        else:
            j3_result = _json_evidence(store, f"{apath}/zarr.json")
            j3, err3 = j3_result.value, j3_result.error
            if isinstance(j3, dict):
                for k, v in _parse_v3_array(j3).items():
                    setattr(lm, k, v)
                lm.present = True
                lm.evidence_state = "PRESENT"
            else:
                lm.present = False
                lm.error = f".zarray: {err} | zarr.json: {err3}"
                lm.evidence_state, lm.evidence_reason = _failed_json_evidence(
                    j_result, j3_result)
        if lm.present and check_chunks:
            _probe_chunk_presence(store, apath, lm, max_flat_keys)
        pm.levels.append(lm)

    if probe_extra_levels > 0:
        numeric = [int(p) for p in declared_paths if p.isdigit()]
        start = (max(numeric) + 1) if numeric else len(datasets)
        for k in range(start, start + probe_extra_levels):
            apath = posixpath.join(root, str(k))
            info = store.head(f"{apath}/.zarray")
            if getattr(info, "exists", False):
                pm.extra_level_dirs.append(str(k))
            else:
                info3 = store.head(f"{apath}/zarr.json")
                if getattr(info3, "exists", False):
                    pm.extra_level_dirs.append(str(k))
                else:
                    break

    return pm


# ---- chunk addressing helpers (used by content spot-checks) ---------------

def chunk_grid(shape: Sequence[int], chunks: Sequence[int]) -> list[int]:
    return [max(1, math.ceil(s / c)) for s, c in zip(shape, chunks)]


def chunk_key(index: Sequence[int], separator: str = ".", zarr_format: int = 2) -> str:
    body = separator.join(str(int(i)) for i in index)
    return body if zarr_format == 2 else f"c{separator}{body}"


def expected_shape(base: Sequence[int], factor: Sequence[float],
                   mode: str = "ceil") -> list[int]:
    """
    Shape a level *should* have given the base shape and a downsample factor.

    Both conventions are seen in real pipelines and neither is wrong on its
    own -- what matters is that a pyramid is INTERNALLY consistent. Callers
    should accept a level that matches either and flag one that matches
    neither.
    """
    f = math.ceil if mode == "ceil" else math.floor
    out: list[int] = []
    for s, fac in zip(base, factor):
        if fac <= 0:
            out.append(int(s))
        else:
            out.append(max(1, int(f(s / fac))))
    return out
