"""
chunkscan.py -- sampled chunk-content probing for Zarr pyramids.

The header-only audit (bin/audit_pyramid.py) answers "are chunk keys
present?". This module answers the next question: "do the chunks that are
present actually hold data?" A chunk that exists on disk but decodes to
all fill_value is the next silent-corruption class -- zarr.open() succeeds,
reads return plausible voxels, nothing raises.

Design notes:
  - Sampling, not census: K chunks per level spread across the chunk grid
    (first / middle / last). A level where every sampled chunk is empty is
    flagged for human review; a level where any sampled chunk holds real
    data is confirmed populated. Absence of a flag is not proof of health.
  - An all-fill chunk is *suspicious*, not proof of corruption: genuinely
    empty background regions exist. Hence CHUNK_SAMPLE_ALL_EMPTY is medium
    severity, and the positive POPULATED confirmation is the primary output.
  - Two-phase fetch for uncompressed chunks: read the first 4 KiB; any
    nonzero byte proves the chunk is populated without downloading the rest.
    Only fully-zero prefixes trigger the full download.
  - Decodable today: zarr v2 raw and v2 blosc. v3 sharded stores and exotic
    codecs (e.g. volcomp) are reported as UNDECODEABLE, never silently
    skipped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

try:
    from numcodecs import Blosc
    _HAS_BLOSC = True
except Exception:  # pragma: no cover
    _HAS_BLOSC = False

from .zarrmeta import chunk_key

PROBE_PREFIX_BYTES = 4096


@dataclass
class ChunkSample:
    root: str
    level: str
    chunk_index: tuple[int, ...]
    key: str
    status: str          # populated | empty | undecodable | fetch_error
    detail: str = ""
    bytes_fetched: int = 0


def sample_indices(grid: list[int], k: int) -> list[tuple[int, ...]]:
    """Spread k sample positions across the flattened chunk grid."""
    total = 1
    for g in grid:
        total *= max(1, g)
    if total <= 0:
        return []
    k = max(1, min(k, total))
    positions = sorted({round(i * (total - 1) / (k - 1)) if k > 1 else 0
                        for i in range(k)})
    out = []
    for p in positions:
        idx, rem = [], p
        for g in reversed(grid):
            g = max(1, g)
            idx.append(rem % g)
            rem //= g
        out.append(tuple(reversed(idx)))
    return out


def _decode(raw: bytes, dtype: str, compressor_id: str) -> np.ndarray | None:
    """Decode one chunk's bytes to a flat array. None => cannot decode."""
    cid = (compressor_id or "none").lower()
    payload = raw
    if cid != "none":
        if cid.startswith("blosc"):
            if not _HAS_BLOSC:
                return None
            try:
                payload = Blosc().decode(raw)
            except Exception:
                return None
        else:
            # sharded v3, volcomp, zstd, ...: out of scope, report don't guess
            return None
    try:
        dt = np.dtype(dtype)
    except Exception:
        return None
    if len(payload) < dt.itemsize:
        return None
    return np.frombuffer(payload[: len(payload) // dt.itemsize * dt.itemsize],
                         dtype=dt)


def _is_fill(arr: np.ndarray, fill_value) -> bool:
    try:
        if fill_value is None:
            fill_value = 0
        if isinstance(fill_value, float) and math.isnan(fill_value):
            return bool(np.isnan(arr).all())
        return bool((arr == fill_value).all())
    except Exception:
        return False


def probe_chunk(store, root: str, level: str, index: tuple[int, ...],
                *, shape, chunks, dtype: str, fill_value,
                compressor_id: str, separator: str,
                zarr_format: int = 2) -> ChunkSample:
    """Probe one chunk. Returns populated/empty/undecodable/fetch_error."""
    key = chunk_key(index, separator=separator or ".",
                    zarr_format=zarr_format or 2)
    path = f"{root}/{level}/{key}"
    sample = ChunkSample(root=root, level=level, chunk_index=index, key=key,
                         status="fetch_error")
    cid = (compressor_id or "none").lower()
    # Existence check first: sparse pyramids legitimately lack most chunk
    # keys, and a missing key is not an error -- just not a useful sample.
    # Both store backends report absence via ObjectInfo.exists (they do not
    # raise for a missing key).
    try:
        info = store.head(path)
        if not getattr(info, "exists", False):
            sample.status = "absent"
            sample.detail = "chunk key not present (sparse level)"
            return sample
    except Exception as exc:
        sample.detail = f"existence check failed: {exc}"
        return sample
    try:
        if cid == "none":
            # Two-phase: a nonzero byte in the prefix proves population.
            head = store.get_range(path, 0, PROBE_PREFIX_BYTES)
            sample.bytes_fetched += len(head)
            if any(head):
                sample.status = "populated"
                sample.detail = (f"nonzero byte in first {len(head)}B "
                                 f"prefix; full chunk not fetched")
                return sample
            raw = store.get(path)
            sample.bytes_fetched += len(raw)
        else:
            raw = store.get(path)
            sample.bytes_fetched += len(raw)
    except Exception as exc:
        sample.detail = f"fetch failed: {exc}"
        return sample
    arr = _decode(raw, dtype, compressor_id)
    if arr is None:
        sample.status = "undecodable"
        sample.detail = (f"cannot decode: compressor={compressor_id} "
                         f"dtype={dtype} zarr_format={zarr_format}")
        return sample
    if _is_fill(arr, fill_value):
        sample.status = "empty"
        sample.detail = (f"{arr.size} values all == fill_value "
                         f"({fill_value!r}); {len(raw)} bytes on disk")
    else:
        nz = int((arr != (0 if fill_value is None else fill_value)).sum()) \
            if not (isinstance(fill_value, float)
                    and fill_value is not None
                    and math.isnan(fill_value)) else int((~np.isnan(arr)).sum())
        sample.status = "populated"
        sample.detail = f"{nz}/{arr.size} values differ from fill_value"
    return sample


def probe_level(store, root: str, level_rec: dict,
                samples_per_level: int = 3) -> list[ChunkSample]:
    """Probe K *present* chunks of one level record.

    Generates 3xK spread candidates and keeps the first K whose keys exist,
    so sparse levels still yield useful samples instead of fetch errors.
    """
    shape = level_rec.get("shape")
    chunks = level_rec.get("chunks")
    if not shape or not chunks or len(shape) != len(chunks):
        return []
    grid = [max(1, math.ceil(s / c)) if c else 1
            for s, c in zip(shape, chunks)]
    kw = dict(
        shape=shape, chunks=chunks,
        dtype=level_rec.get("dtype") or "uint8",
        fill_value=level_rec.get("fill_value"),
        compressor_id=level_rec.get("compressor") or "none",
        separator=level_rec.get("dimension_separator") or ".",
        zarr_format=level_rec.get("zarr_format") or 2,
    )
    out = []
    for idx in sample_indices(grid, samples_per_level * 3):
        if len(out) >= samples_per_level:
            break
        s = probe_chunk(store, root, str(level_rec.get("level")), idx, **kw)
        if s.status == "absent":
            continue
        out.append(s)
    return out
