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
