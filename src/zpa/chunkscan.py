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
  - Two-phase fetch for uncompressed integer chunks with a zero fill: read
    the first 4 KiB; any nonzero byte proves the chunk is populated without
    downloading the rest. Only fully-zero prefixes trigger the full
    download. Any other fill value (255, "NaN", ...) is decoded in full,
    because a nonzero byte proves nothing there.
  - Decodable today: zarr v2 raw and v2 blosc; unsharded v3 raw ("bytes");
    v3 sharded levels whose inner codec is volcomp (the dl.ash2txt.org
    scroll volumes), decoded with a vendored libvolcomp over HTTP byte
    ranges. Other v3 sharded
    stores and exotic codecs are reported as UNDECODEABLE, never silently
    skipped.
"""

from __future__ import annotations

import math
import re
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
    #                      (+ missing | absent | index_checksum_mismatch)
    detail: str = ""
    bytes_fetched: int = 0
    # Shard-index CRC32C evidence for sharded probes: "verified" |
    # "mismatch" | "unchecksummed" (index has no crc32c codec); "" elsewhere.
    index_crc: str = ""


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
    # A v3 codec chain of just "bytes" is an uncompressed chunk; the bytes
    # codec's default (and the only one zarr writers emit in practice) is
    # little-endian, applied explicitly below.
    if cid not in ("none", "bytes"):
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
        if cid == "bytes" and dt.itemsize > 1:
            dt = dt.newbyteorder("<")
    except Exception:
        return None
    if len(payload) < dt.itemsize:
        return None
    return np.frombuffer(payload[: len(payload) // dt.itemsize * dt.itemsize],
                         dtype=dt)


_SPECIAL_FLOATS = {"nan": float("nan"), "infinity": float("inf"),
                   "-infinity": float("-inf")}


def _fill_scalar(fill_value):
    """Normalise a header fill_value to a comparable scalar.

    Zarr v2 JSON encodes non-finite floats as the strings "NaN",
    "Infinity" and "-Infinity"; a missing fill_value reads as 0.
    """
    if fill_value is None:
        return 0
    if isinstance(fill_value, str):
        special = _SPECIAL_FLOATS.get(fill_value.lower())
        if special is not None:
            return special
    return fill_value


def _is_nan(value) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _is_fill(arr: np.ndarray, fill_value) -> bool:
    try:
        fill_value = _fill_scalar(fill_value)
        if _is_nan(fill_value):
            return bool(np.isnan(arr).all())
        return bool((arr == fill_value).all())
    except Exception:
        return False


def _n_not_fill(arr: np.ndarray, fill_value) -> int:
    fill_value = _fill_scalar(fill_value)
    if _is_nan(fill_value):
        return int((~np.isnan(arr)).sum())
    return int((arr != fill_value).sum())


def _prefix_proves_population(dtype: str, fill_value) -> bool:
    """A nonzero raw byte proves non-fill data only for an all-zero-bytes
    fill on an integer dtype (a float -0.0 equals a 0.0 fill)."""
    try:
        kind = np.dtype(dtype).kind
    except Exception:
        return False
    fill_value = _fill_scalar(fill_value)
    return (kind in "biu" and not isinstance(fill_value, str)
            and not _is_nan(fill_value) and fill_value == 0)


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
    # Strict range reads fail closed on a short body, so never ask for more
    # prefix than the object holds: a chunk smaller than the probe prefix
    # would otherwise be reported as a fetch error instead of probed.
    size = getattr(info, "size", None)
    prefix = PROBE_PREFIX_BYTES
    if isinstance(size, int) and not isinstance(size, bool) and size > 0:
        prefix = min(prefix, size)
    try:
        if cid == "none" and _prefix_proves_population(dtype, fill_value):
            # Two-phase: with a zero fill, a nonzero byte in the prefix
            # proves population.
            head = store.get_range(path, 0, prefix)
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
        nz = _n_not_fill(arr, fill_value)
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


def probe_level_v3_sharded(bucket: str, root: str, level_rec: dict,
                           samples_per_level: int = 3,
                           endpoint_url: str | None = None) -> list[ChunkSample]:
    """Probe a v3 sharded level via zarr-python + s3fs.

    Opens the array and reads small windows at spread positions. A window
    with any non-fill value proves population. Used for levels whose
    chunks are sharded (sharding_indexed) and not directly addressable.
    Only supports s3:// buckets (anonymous).
    """
    import warnings
    warnings.filterwarnings("ignore")
    shape = level_rec.get("shape") or []
    if not shape:
        return []
    level = str(level_rec.get("level"))
    fill_value = level_rec.get("fill_value")
    if fill_value is None:
        fill_value = 0
    out: list[ChunkSample] = []
    try:
        import s3fs
        from zarr.storage import FsspecStore
        import zarr
        kw: dict = {"anon": True}
        if endpoint_url:
            kw["client_kwargs"] = {"endpoint_url": endpoint_url}
        fs = s3fs.S3FileSystem(**kw)
        prefix = f"{bucket}/{root}/{level}".replace("s3://", "")
        mapper = fs.get_mapper(prefix, check=False)
        arr = zarr.open_array(store=FsspecStore.from_mapper(mapper), mode="r")
    except Exception as exc:
        out.append(ChunkSample(root=root, level=level, chunk_index=(),
                               key=f"{level}/<shards>",
                               status="undecodable",
                               detail=f"zarr open failed: {exc}"))
        return out
    # window size: small but meaningful; spread positions across the array
    wins = [min(64, s) for s in shape]
    if len(wins) > 3:
        wins = wins[:3]
    positions = []
    k = samples_per_level
    for i in range(k):
        pos = []
        for dim, (s, w) in enumerate(zip(shape[: len(wins)], wins)):
            span = max(0, s - w)
            # spread: 15%, 50%, 85% along each axis, cycled per sample
            frac = (0.15, 0.5, 0.85)[i % 3] if k > 1 else 0.5
            # offset the fraction per dimension so samples don't line up
            frac = (frac + 0.23 * dim) % 1.0
            pos.append(int(span * frac))
        positions.append(tuple(pos))
    for p in positions:
        sl = tuple(slice(o, o + w) for o, w in zip(p, wins))
        try:
            data = arr[sl]
            nz = int((data != fill_value).sum())
            status = "populated" if nz else "empty"
            detail = (f"window {p}+{tuple(wins)}: {nz}/{data.size} values "
                      f"differ from fill_value ({fill_value!r})")
        except Exception as exc:
            status, nz, detail = "fetch_error", 0, f"window read failed: {exc}"
        out.append(ChunkSample(root=root, level=level, chunk_index=p,
                               key=f"{level}/<shard-window>",
                               status=status, detail=detail))
    return out


class _ShardAbsent(Exception):
    """The shard object is confirmed absent (404): masked background."""


class _ShardTooSmall(Exception):
    """The server says the shard is smaller than its own index (416)."""


def _read_shard_index(store, skey: str, idx_size: int) -> bytes:
    """Fetch the trailing ``idx_size`` bytes of a shard, strictly.

    Uses the store's fail-closed ``get_suffix``. Servers that reject suffix
    ranges outright (e.g. 400/501) get one fallback: the object size from
    ``head`` and an explicit, equally strict ``get_range``.
    """
    from .httpstore import StoreError

    try:
        return store.get_suffix(skey, idx_size)
    except StoreError as exc:
        msg = str(exc)
        if msg.startswith("404 Not Found") or "FileNotFoundError" in msg:
            raise _ShardAbsent(msg) from exc
        if "HTTP 416" in msg:
            raise _ShardTooSmall(
                f"shard smaller than its index (suffix {idx_size}B "
                f"unsatisfiable)") from exc
        if not re.search(r"HTTP (400|405|501)\b", msg):
            raise
    info = store.head(skey)
    if not getattr(info, "exists", False):
        if getattr(info, "status", None) == 404:
            raise _ShardAbsent(f"404 Not Found: {skey}")
        raise StoreError(f"shard size probe failed: {info.error or info.status}")
    total = info.size
    if not isinstance(total, int):
        raise StoreError(f"shard size unknown after suffix range was rejected: {skey}")
    if total < idx_size:
        raise _ShardTooSmall(f"shard smaller than its index ({total} < {idx_size})")
    return store.get_range(skey, total - idx_size, idx_size)


def probe_level_volcomp_sharded(store, root: str, level_rec: dict,
                               samples_per_level: int = 3,
                               inner_per_shard: int = 3) -> list[ChunkSample]:
    """Probe a v3 sharded level whose inner codec is volcomp.

    Parses the sharding_indexed shard indexes with strict suffix/byte-range
    reads (any store: HTTP, S3, local) and decodes sampled 128^3 inner
    chunks with the vendored libvolcomp -- no zarr-python, no event loop,
    proxy-friendly.  Statuses:
    populated | empty (present, decodes to fill) | missing (absent from
    the shard index; reads as fill legitimately) | undecodable |
    fetch_error.
    """
    import numpy as np

    from . import volcomp as vc

    level = str(level_rec.get("level"))
    fill_value = level_rec.get("fill_value")
    if fill_value is None:
        fill_value = 0
    out: list[ChunkSample] = []

    def fail(status, detail, idx=()):
        out.append(ChunkSample(root=root, level=level, chunk_index=idx,
                               key=f"{level}/<volcomp>", status=status,
                               detail=detail))
        return out

    ok, reason = vc.available()
    if not ok:
        return fail("undecodable", f"volcomp unavailable: {reason}")
    try:
        meta = store.get_json(f"{root}/{level}/zarr.json")
    except Exception as exc:
        return fail("fetch_error", f"zarr.json unreadable: {exc}")
    info = vc.parse_zarr_json(meta)
    if info is None:
        return fail("undecodable", "zarr.json has no sharding_indexed codec")
    if info.inner_codec != "volcomp":
        return fail("undecodable",
                    f"inner codec is {info.inner_codec!r}, not volcomp")
    if info.index_location != "end":
        # The probe fetches the shard tail; for a start-located index that is
        # chunk payload, which would parse into garbage offsets.
        return fail("undecodable",
                    f"index_location={info.index_location!r} unsupported "
                    f"(probe reads the index from the shard tail)")

    shard_grid = [max(1, (s + o - 1) // o)
                  for s, o in zip(info.shape, info.outer_chunks)]
    for sc in sample_indices(shard_grid, samples_per_level):
        skey = vc.shard_key(root, level, sc)
        cps = vc.inner_chunks_per_shard(info, sc)
        n_inner = 1
        for c in cps:
            n_inner *= c
        try:
            idx_size = vc.index_encoded_size(n_inner, info.index_codecs)
        except ValueError as exc:
            return fail("undecodable", str(exc), sc)
        # The shard index sits at the very end of the shard object: one
        # strict suffix read fetches it. A response that cannot prove it is
        # the tail (bad/missing Content-Range, short body) fails closed
        # instead of being parsed as an index.
        try:
            raw_index = _read_shard_index(store, skey, idx_size)
        except _ShardAbsent:
            out.append(ChunkSample(
                root=root, level=level, chunk_index=sc,
                key=f"{level}/c/" + "/".join(map(str, sc)),
                status="missing",
                detail="shard object absent (reads as fill)"))
            continue
        except _ShardTooSmall as exc:
            return fail("undecodable", str(exc), sc)
        except Exception as exc:
            return fail("fetch_error", f"shard index fetch failed: {exc}", sc)
        fetched = len(raw_index)  # index bytes
        entries = vc.parse_index(raw_index, n_inner, info.index_codecs)
        if entries is None:
            return fail("fetch_error", "shard index failed to parse", sc)
        crc_ok = vc.verify_index_checksum(raw_index, info.index_codecs)
        if crc_ok is False:
            # The index parses but its offsets cannot be trusted, so no
            # chunk payload is read from this shard. Other shards are still
            # sampled. Not proof the data is bad -- a non-conforming writer
            # would look the same -- hence a review flag, not a verdict.
            out.append(ChunkSample(
                root=root, level=level, chunk_index=sc,
                key=f"{level}/c/" + "/".join(map(str, sc)),
                status="index_checksum_mismatch",
                detail=("shard index crc32c does not match its stored "
                        "checksum; inner-chunk offsets untrusted, shard "
                        "not sampled"),
                bytes_fetched=len(raw_index), index_crc="mismatch"))
            continue
        index_crc = "verified" if crc_ok else "unchecksummed"
        for ic in sample_indices(list(cps), inner_per_shard):
            flat = 0
            mult = 1
            for dim in reversed(range(len(cps))):
                flat += ic[dim] * mult
                mult *= cps[dim]
            off, ln = entries[flat]
            # global inner-chunk coords, for edge cropping
            gic = tuple(sc[d] * (info.outer_chunks[d] // info.inner_chunks[d])
                        + ic[d] for d in range(len(cps)))
            key = (f"{level}/c/" + "/".join(map(str, sc)) +
                   f"#{'.'.join(map(str, ic))}")
            if off == vc.MISSING or ln == vc.MISSING:
                out.append(ChunkSample(
                    root=root, level=level, chunk_index=gic, key=key,
                    status="missing",
                    detail="inner chunk absent from shard index",
                    index_crc=index_crc))
                continue
            try:
                blob = store.get_range(skey, off, ln)
                fetched += len(blob)
            except Exception as exc:
                out.append(ChunkSample(
                    root=root, level=level, chunk_index=gic, key=key,
                    status="fetch_error", detail=f"chunk fetch failed: {exc}",
                    bytes_fetched=fetched, index_crc=index_crc))
                fetched = 0
                continue
            # cheap first pass: decode the central 16^3 block only
            blk = vc.decode_block(blob, 4, 4, 4)
            nz = sum(1 for b in blk if b != fill_value) if blk else 0
            if nz:
                status, detail = "populated", (
                    f"center 16^3 block: {nz}/4096 differ from fill "
                    f"({fill_value!r}); {len(blob)} stored bytes")
            else:
                full = vc.decode_chunk(blob)
                if full is None:
                    status, detail = ("undecodable",
                                      "volcomp decode failed (corrupt stream?)")
                else:
                    # crop edge chunks to the valid region
                    arr = np.frombuffer(full, dtype=np.uint8).reshape(
                        (128,) * len(cps))
                    sl = tuple(
                        slice(0, min(info.inner_chunks[d],
                                     info.shape[d] - gic[d] * info.inner_chunks[d]))
                        for d in range(len(cps)))
                    nz = int((arr[sl] != fill_value).sum())
                    status = "populated" if nz else "empty"
                    detail = (f"{nz}/{arr[sl].size} valid voxels differ from "
                              f"fill ({fill_value!r}); {len(blob)} stored bytes")
            out.append(ChunkSample(root=root, level=level, chunk_index=gic,
                                   key=key, status=status, detail=detail,
                                   bytes_fetched=fetched,
                                   index_crc=index_crc))
            fetched = 0
    return out


# Severity of every finding the chunk-content probe can emit. Part of the
# public contract (``zpa.report.contract()["chunk_scan_codes"]``).
SCAN_SEVERITY = {
    "CHUNK_SAMPLE_POPULATED": "info",
    "CHUNK_SAMPLE_EMPTY": "info",
    "CHUNK_SAMPLE_MISSING": "info",
    "CHUNK_SAMPLE_ABSENT": "info",
    "CHUNK_LEVEL_NO_CHUNKS": "info",
    "CHUNK_LEVEL_NO_SAMPLES": "info",
    "CHUNK_UNDECODEABLE": "low",
    "CHUNK_FETCH_ERROR": "low",
    # 2026-10-03: raised to medium after byte-level verification proved the
    # volcomp writer is non-conforming (16.5% of 2,008 shards across 39/64
    # volumes; independent bit-by-bit CRC implementation confirms zpa is
    # correct). Not high: the index parses and chunks decode; the integrity
    # guarantee is void, not the data. See
    # artifacts/2026-10-03-crc-byte-verification/README.md.
    "SHARD_INDEX_CHECKSUM_MISMATCH": "medium",
    "CHUNK_SAMPLE_ALL_EMPTY": "medium",
}

# Sample status -> finding code. Any other status (fetch_error) is
# FALLBACK_STATUS_CODE.
STATUS_CODES = {
    "populated": "CHUNK_SAMPLE_POPULATED",
    "empty": "CHUNK_SAMPLE_EMPTY",
    "missing": "CHUNK_SAMPLE_MISSING",
    "absent": "CHUNK_SAMPLE_ABSENT",
    "undecodable": "CHUNK_UNDECODEABLE",
    "index_checksum_mismatch": "SHARD_INDEX_CHECKSUM_MISMATCH",
}
FALLBACK_STATUS_CODE = "CHUNK_FETCH_ERROR"


def classify_level(root: str, level: str, has_chunks,
                   samples: list[ChunkSample],
                   n_candidates: int = 9) -> tuple[list[dict], bool]:
    """Turn one level's probe samples into findings.

    Returns ``(findings, all_empty)``. Only *present, decodable* samples
    count toward ``CHUNK_SAMPLE_ALL_EMPTY``: a key absent from a listing or
    shard index is masked background (missing != empty), and a fetch or
    decode failure is no evidence either way.
    """
    out: list[dict] = []

    def emit(code, chunk="", detail="", bf=0):
        out.append({"code": code, "severity": SCAN_SEVERITY[code],
                    "root": root, "level": level, "chunk": chunk,
                    "detail": detail, "bytes_fetched": bf})

    if not samples:
        if has_chunks is False:
            # Audit-flagged chunkless level, confirmed: no chunk keys among
            # the probe's spread candidates.
            emit("CHUNK_LEVEL_NO_CHUNKS",
                 detail=("level holds no stored chunks (audit: "
                         f"has_chunks=false; probe: no keys among "
                         f"{n_candidates} spread candidates)"))
        else:
            # Sparse level the spread sampling couldn't cover: not evidence
            # of absence, reported as a coverage gap rather than a finding.
            emit("CHUNK_LEVEL_NO_SAMPLES",
                 detail=(f"no chunk keys among {n_candidates} spread "
                         "candidates; sparse level not coverable by spread "
                         "sampling"))
        return out, False
    for smp in samples:
        emit(STATUS_CODES.get(smp.status, FALLBACK_STATUS_CODE),
             ".".join(map(str, smp.chunk_index)), smp.detail,
             smp.bytes_fetched)
    decodable = [smp for smp in samples if smp.status in ("populated", "empty")]
    all_empty = bool(decodable) and all(smp.status == "empty" for smp in decodable)
    if all_empty:
        emit("CHUNK_SAMPLE_ALL_EMPTY",
             detail=(f"all {len(decodable)} sampled chunks decode to "
                     "fill_value; human review needed"))
    return out, all_empty
