"""volcomp.py -- decode support for Zarr v3 levels using the volcomp codec.

The scroll volumes on dl.ash2txt.org are Zarr v3 with the codec chain::

    sharding_indexed  (1024^3 outer shards, 128^3 inner chunks)
      -> volcomp       (lossy u8 CT codec; q=8.0 on the public volumes)

volcomp is a third-party MIT-licensed C codec
(https://github.com/superoptimizer/volume-compressor).  This module:

  * loads the vendored ``libvolcomp`` (Linux x86-64) -- or ``$VOLCOMP_LIB``
    -- through ctypes; only the decode entry points are used,
  * parses ``sharding_indexed`` shard indexes directly from HTTP byte
    ranges, so no zarr-python (and no aiohttp event loop) is needed,
  * decodes sampled inner chunks and classifies them as
    populated / empty / missing / undecodable.

On platforms without a usable library, every entry point degrades to a
clear "volcomp unavailable" result instead of raising.
"""

from __future__ import annotations

import ctypes
import os
import platform
import struct
import sys
from dataclasses import dataclass

CHUNK_VOXELS = 128 ** 3
MISSING = (1 << 64) - 1  # sharding_indexed marks absent inner chunks this way

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_VENDORED = os.path.join(_DATA_DIR, "libvolcomp-linux-x86_64.so")

_lib = None
_lib_reason = "not attempted"


def _load():
    """Load libvolcomp once; return (CDLL|None, reason)."""
    global _lib, _lib_reason
    if _lib is not None or _lib_reason != "not attempted":
        return _lib, _lib_reason
    path = os.environ.get("VOLCOMP_LIB")
    if not path:
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            _lib_reason = (
                f"vendored libvolcomp is Linux x86-64 only "
                f"(this is {platform.system()} {platform.machine()}); "
                f"set VOLCOMP_LIB to a local build"
            )
            return None, _lib_reason
        if not os.path.exists(_VENDORED):
            _lib_reason = f"vendored library missing: {_VENDORED}"
            return None, _lib_reason
        path = _VENDORED
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        _lib_reason = f"could not load {path}: {e}"
        return None, _lib_reason
    try:
        lib.volcomp_shim_decode.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_void_p, ctypes.c_size_t,
        ]
        lib.volcomp_shim_decode.restype = ctypes.c_int
        lib.volcomp_shim_decode_block.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_size_t,
        ]
        lib.volcomp_shim_decode_block.restype = ctypes.c_int
    except AttributeError as e:
        _lib_reason = f"{path} lacks the expected ABI: {e}"
        return None, _lib_reason
    _lib = lib
    _lib_reason = "ok"
    return _lib, _lib_reason


def available() -> tuple[bool, str]:
    """(True, 'ok') if volcomp decoding is usable, else (False, reason)."""
    lib, reason = _load()
    return (lib is not None), reason


def decode_chunk(blob: bytes) -> bytes | None:
    """Decode one 128^3 volcomp inner chunk; None on failure."""
    lib, _ = _load()
    if lib is None:
        return None
    dst = ctypes.create_string_buffer(CHUNK_VOXELS)
    rc = lib.volcomp_shim_decode(blob, len(blob), dst, CHUNK_VOXELS)
    if rc != 0:
        return None
    return dst.raw


def decode_block(blob: bytes, bz: int, by: int, bx: int) -> bytes | None:
    """Decode one 16^3 block of a volcomp chunk; None on failure."""
    lib, _ = _load()
    if lib is None:
        return None
    dst = ctypes.create_string_buffer(16 ** 3)
    rc = lib.volcomp_shim_decode_block(blob, len(blob), bz, by, bx,
                                       dst, 16 ** 3)
    if rc != 0:
        return None
    return dst.raw


# ---------------------------------------------------------------------------
# sharding_indexed parsing (byte-range friendly; mirrors zarr-python's layout)
# ---------------------------------------------------------------------------

@dataclass
class ShardingInfo:
    outer_chunks: tuple[int, ...]   # e.g. (1024, 1024, 1024)
    inner_chunks: tuple[int, ...]   # e.g. (128, 128, 128)
    shape: tuple[int, ...]
    inner_codec: str               # e.g. "volcomp"
    index_codecs: list[str]


def parse_zarr_json(meta: dict) -> ShardingInfo | None:
    """Extract sharding info from a v3 zarr.json; None if not sharded."""
    try:
        grid = meta["chunk_grid"]
        outer = tuple(grid["configuration"]["chunk_shape"])
        shape = tuple(meta["shape"])
        for codec in meta["codecs"]:
            if codec.get("name") == "sharding_indexed":
                cfg = codec["configuration"]
                inner = tuple(cfg["chunk_shape"])
                inner_codecs = [c.get("name", "?") for c in cfg.get("codecs", [])]
                index_codecs = [c.get("name", "?")
                                for c in cfg.get("index_codecs", [])]
                inner_codec = inner_codecs[0] if inner_codecs else "?"
                return ShardingInfo(outer, inner, shape, inner_codec,
                                    index_codecs)
    except (KeyError, TypeError, ValueError):
        pass
    return None


def index_encoded_size(n_inner: int, index_codecs: list[str]) -> int:
    """Byte size of the encoded shard index stored at the shard's tail."""
    size = 16 * n_inner
    for name in index_codecs:
        if name == "bytes":
            continue
        if name == "crc32c":
            size += 4
            continue
        raise ValueError(f"unsupported index codec: {name}")
    return size


def parse_index(raw: bytes, n_inner: int,
                index_codecs: list[str]) -> list[tuple[int, int]] | None:
    """Parse an encoded shard index into [(offset, length)] in C order.

    ``raw`` is the last ``index_encoded_size(n_inner, index_codecs)`` bytes
    of the shard.  Returns None on structural problems.  Entries equal to
    (2**64-1, 2**64-1) are missing inner chunks.
    """
    if "crc32c" in index_codecs:
        raw = raw[:-4]  # trailing checksum; length already constrains it
    if len(raw) != 16 * n_inner:
        return None
    return [struct.unpack_from("<QQ", raw, i * 16) for i in range(n_inner)]


def inner_chunks_per_shard(info: ShardingInfo,
                           shard_coords: tuple[int, ...]) -> tuple[int, ...]:
    """Inner-chunk grid shape for one shard (edge shards may be partial)."""
    start = tuple(c * o for c, o in zip(shard_coords, info.outer_chunks))
    return tuple(
        min(o // ic, (s - st + ic - 1) // ic)
        for o, ic, s, st in zip(info.outer_chunks, info.inner_chunks,
                                info.shape, start)
    )


def shard_key(root: str, level: str, coords: tuple[int, ...]) -> str:
    return f"{root}/{level}/c/" + "/".join(str(c) for c in coords)
