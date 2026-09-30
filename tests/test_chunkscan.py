"""Unit tests for the network-free core of lib/chunkscan.py.

Run: python3 -m pytest tests/ -q   (or: .venv/bin/python -m pytest tests/ -q)
"""

import sys

import numpy as np
import pytest

from zpa.chunkscan import _decode, _is_fill, sample_indices


def test_sample_indices_spread_1d():
    idx = sample_indices([10], 3)
    assert idx[0] == (0,)
    assert idx[-1] == (9,)
    assert len(idx) == 3


def test_sample_indices_capped_at_grid_size():
    idx = sample_indices([2, 2], 99)
    assert len(idx) == 4
    assert len(set(idx)) == 4


def test_sample_indices_single_sample():
    assert sample_indices([5, 5, 5], 1) == [(0, 0, 0)]


def test_sample_indices_known_positions():
    # 4 positions over a 4-wide grid -> corners exactly
    assert sample_indices([4], 4) == [(0,), (1,), (2,), (3,)]


def test_decode_raw_roundtrip():
    arr = np.arange(24, dtype=np.uint8)
    out = _decode(arr.tobytes(), "uint8", "none")
    assert out is not None
    assert (out == arr).all()


def test_decode_raw_truncates_to_dtype():
    raw = b"\x01\x02\x03"  # 3 bytes, uint16 -> 1 element
    out = _decode(raw, "uint16", "none")
    assert out is not None and out.shape == (1,)


def test_decode_blosc_roundtrip():
    pytest.importorskip("numcodecs")
    from numcodecs import Blosc
    arr = np.arange(100, dtype=np.uint8)
    raw = Blosc().encode(arr.tobytes())
    out = _decode(raw, "uint8", "blosc")
    assert out is not None
    assert (out == arr).all()


def test_decode_unknown_codec_returns_none():
    out = _decode(b"\x00" * 64, "uint8", "zstd")
    assert out is None


def test_decode_bad_dtype_returns_none():
    assert _decode(b"\x00" * 64, "not-a-dtype", "none") is None


def test_is_fill_zeros():
    assert _is_fill(np.zeros(10, dtype=np.uint8), 0) is True
    assert _is_fill(np.zeros(10, dtype=np.uint8), None) is True


def test_is_fill_nonzero():
    arr = np.zeros(10, dtype=np.uint8)
    arr[5] = 7
    assert _is_fill(arr, 0) is False


def test_is_fill_nan():
    arr = np.full(10, np.nan)
    assert _is_fill(arr, float("nan")) is True
    assert _is_fill(np.zeros(10), float("nan")) is False
