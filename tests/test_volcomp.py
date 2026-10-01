"""Tests for the volcomp shard-index parsing and decode path (no network)."""

import struct
import sys

import pytest

from zpa import volcomp as vc


def _meta(inner="volcomp", index_codecs=("bytes", "crc32c")):
    return {
        "shape": [9598, 7837, 7837],
        "chunk_grid": {"configuration": {"chunk_shape": [1024, 1024, 1024]}},
        "codecs": [
            {"name": "sharding_indexed",
             "configuration": {
                 "chunk_shape": [128, 128, 128],
                 "codecs": [{"name": inner, "configuration": {"q": 8.0}}],
                 "index_codecs": [{"name": n} for n in index_codecs],
             }},
        ],
    }


def test_parse_zarr_json_ok():
    info = vc.parse_zarr_json(_meta())
    assert info is not None
    assert info.outer_chunks == (1024, 1024, 1024)
    assert info.inner_chunks == (128, 128, 128)
    assert info.inner_codec == "volcomp"
    assert info.index_codecs == ["bytes", "crc32c"]


def test_parse_zarr_json_not_sharded():
    assert vc.parse_zarr_json({"codecs": [{"name": "bytes"}]}) is None
    assert vc.parse_zarr_json({}) is None


def test_index_roundtrip():
    n = 8 * 8 * 8
    entries = [(i * 100, 50 + i) for i in range(n)]
    entries[3] = (vc.MISSING, vc.MISSING)
    raw = b"".join(struct.pack("<QQ", o, ln) for o, ln in entries)
    raw_crc = raw + b"\x00\x00\x00\x00"  # checksum bytes are skipped
    got = vc.parse_index(raw_crc, n, ["bytes", "crc32c"])
    assert got == entries


def test_index_bad_length():
    assert vc.parse_index(b"\x00" * 10, 8, ["bytes"]) is None


def test_index_encoded_size():
    assert vc.index_encoded_size(512, ["bytes", "crc32c"]) == 512 * 16 + 4
    assert vc.index_encoded_size(8, ["bytes"]) == 8 * 16
    with pytest.raises(ValueError):
        vc.index_encoded_size(8, ["zstd"])


def test_inner_chunks_per_shard_edge():
    info = vc.parse_zarr_json(_meta())
    # full shard
    assert vc.inner_chunks_per_shard(info, (0, 0, 0)) == (8, 8, 8)
    # edge shard: 9598 -> 9 full 1024-shards + 382 -> 3 inner;
    # 7837 -> 7 full + 669 -> 6 inner
    assert vc.inner_chunks_per_shard(info, (9, 7, 7)) == (3, 6, 6)


def test_shard_key():
    assert vc.shard_key("r", "0", (1, 2, 3)) == "r/0/c/1/2/3"


def test_decode_real_chunk():
    """Decode path against the vendored lib (skipped without it)."""
    ok, reason = vc.available()
    if not ok:
        pytest.skip(f"volcomp unavailable: {reason}")
    # a volcomp stream too short to be valid must fail cleanly, not crash
    assert vc.decode_chunk(b"\x00" * 16) is None
    assert vc.decode_block(b"\x00" * 16, 0, 0, 0) is None


# ---- shard-index CRC32C verification -----------------------------------------
# parse_index() deliberately skips the trailing checksum (pinned by
# test_index_roundtrip above); verification is a separate, opt-in function.

def _real_shard(tmp_path, *, index_location="end"):
    """Have zarr-python write a real sharded array; return (raw shard, n_inner)."""
    import numpy as np
    import zarr
    from zarr.codecs import BytesCodec, Crc32cCodec, ShardingCodec
    arr = zarr.create_array(
        zarr.storage.LocalStore(str(tmp_path)), shape=(8, 8, 8),
        chunks=(8, 8, 8), dtype="u1", fill_value=0, zarr_format=3,
        compressors=None,   # a default outer compressor would wrap the whole shard
        serializer=ShardingCodec(
            chunk_shape=(4, 4, 4), codecs=[BytesCodec()],
            index_codecs=[BytesCodec(), Crc32cCodec()],
            index_location=index_location),
    )
    arr[:] = np.arange(512, dtype="u1").reshape(8, 8, 8)
    return (tmp_path / "c" / "0" / "0" / "0").read_bytes(), 8


def test_crc32c_known_vector_and_empty():
    assert vc.crc32c(b"123456789") == 0xE3069283   # CRC-32C check value
    assert vc.crc32c(b"") == 0


def test_pure_python_crc32c_agrees_with_the_fast_path():
    import os
    data = os.urandom(8196)
    assert vc._crc32c_py(data) == vc.crc32c(data)
    assert vc._crc32c_py(b"123456789") == 0xE3069283


def test_verify_accepts_an_index_written_by_zarr_python(tmp_path):
    raw, n = _real_shard(tmp_path)
    size = vc.index_encoded_size(n, ["bytes", "crc32c"])
    tail = raw[-size:]
    assert vc.verify_index_checksum(tail, ["bytes", "crc32c"]) is True
    # and the layout assumptions parse_index relies on agree with zarr's
    entries = vc.parse_index(tail, n, ["bytes", "crc32c"])
    assert entries is not None and len(entries) == n
    assert all(o + ln <= len(raw) - size for o, ln in entries)


def test_verify_rejects_a_flipped_index_byte(tmp_path):
    raw, n = _real_shard(tmp_path)
    size = vc.index_encoded_size(n, ["bytes", "crc32c"])
    tail = bytearray(raw[-size:])
    tail[5] ^= 0x01                       # corrupt one offset byte
    assert vc.verify_index_checksum(bytes(tail), ["bytes", "crc32c"]) is False
    # parse_index still "succeeds" -- exactly the silent failure this closes
    assert vc.parse_index(bytes(tail), n, ["bytes", "crc32c"]) is not None


def test_verify_rejects_a_corrupted_stored_checksum(tmp_path):
    raw, n = _real_shard(tmp_path)
    size = vc.index_encoded_size(n, ["bytes", "crc32c"])
    tail = bytearray(raw[-size:])
    tail[-1] ^= 0xFF
    assert vc.verify_index_checksum(bytes(tail), ["bytes", "crc32c"]) is False


def test_verify_ignores_corruption_outside_the_index(tmp_path):
    # The CRC covers the index only; chunk payload damage is a different
    # failure (caught by decoding) and must not be reported as an index fault.
    raw, n = _real_shard(tmp_path)
    size = vc.index_encoded_size(n, ["bytes", "crc32c"])
    damaged = bytearray(raw)
    damaged[3] ^= 0xFF
    assert vc.verify_index_checksum(bytes(damaged[-size:]),
                                    ["bytes", "crc32c"]) is True


def test_verify_is_not_applicable_without_a_crc32c_codec():
    raw = b"\x00" * (16 * 8)
    assert vc.verify_index_checksum(raw, ["bytes"]) is None


def test_verify_too_short_to_hold_a_checksum_is_a_mismatch():
    assert vc.verify_index_checksum(b"\x00\x01", ["bytes", "crc32c"]) is False


def test_parse_zarr_json_reads_index_location():
    assert vc.parse_zarr_json(_meta()).index_location == "end"   # default
    meta = _meta()
    meta["codecs"][0]["configuration"]["index_location"] = "start"
    assert vc.parse_zarr_json(meta).index_location == "start"
