"""Shard-index CRC32C handling in the volcomp sharded probe (no network).

A corrupt shard index parses fine -- its offsets are just wrong -- so without
verification the probe would read garbage byte ranges and report whatever
those decode to. These tests pin that the checksum is verified, that a
mismatch is a distinct, non-fatal status, and that "not checksummed" and
"verified" are never conflated.
"""
import struct
from types import SimpleNamespace

import pytest

from zpa import volcomp as vc
from zpa.chunkscan import probe_level_volcomp_sharded

SHAPE = [256, 256, 256]          # one 256^3 shard of 2x2x2 inner 128^3 chunks
N_INNER = 8


def meta(index_codecs=("bytes", "crc32c"), index_location=None):
    cfg = {"chunk_shape": [128, 128, 128],
           "codecs": [{"name": "volcomp"}],
           "index_codecs": [{"name": n} for n in index_codecs]}
    if index_location:
        cfg["index_location"] = index_location
    return {"shape": SHAPE,
            "chunk_grid": {"configuration": {"chunk_shape": [256, 256, 256]}},
            "codecs": [{"name": "sharding_indexed", "configuration": cfg}]}


def shard_bytes(*, with_crc=True, flip=None):
    """A shard whose index marks every inner chunk MISSING (nothing to decode)."""
    body = b"".join(struct.pack("<QQ", vc.MISSING, vc.MISSING)
                    for _ in range(N_INNER))
    index = body + (vc.crc32c(body).to_bytes(4, "little") if with_crc else b"")
    if flip is not None:
        index = bytearray(index)
        index[flip] ^= 0x01
        index = bytes(index)
    return b"\xAA" * 64 + index          # arbitrary payload, then the index


class FakeStore:
    def __init__(self, zarr_json, shard):
        self.zarr_json, self.shard = zarr_json, shard
        self.suffix_reads = 0
        self.range_reads = 0

    def get_json(self, path):
        return self.zarr_json

    def get_suffix(self, key, n):
        # the probe reads shard indexes through the store's strict suffix read
        self.suffix_reads += 1
        return self.shard[-n:]

    def get_range(self, key, off, ln):
        self.range_reads += 1
        return self.shard[off:off + ln]


LEVEL = {"level": "0", "fill_value": 0}


def probe(store, **kw):
    return probe_level_volcomp_sharded(store, "root.zarr", LEVEL,
                                       samples_per_level=1,
                                       inner_per_shard=3, **kw)


def test_valid_index_is_verified_and_sampling_proceeds():
    samples = probe(FakeStore(meta(), shard_bytes()))
    assert [s.status for s in samples] == ["missing"] * 3
    assert {s.index_crc for s in samples} == {"verified"}


@pytest.mark.parametrize("flip", [0, 40, 8 * 16 - 1, 8 * 16 + 1])
def test_corrupt_index_or_checksum_is_a_distinct_status(flip):
    store = FakeStore(meta(), shard_bytes(flip=flip))
    samples = probe(store)
    assert [s.status for s in samples] == ["index_checksum_mismatch"]
    assert samples[0].index_crc == "mismatch"
    assert "crc32c" in samples[0].detail.lower()
    # the untrustworthy offsets were never used to read chunk payloads
    assert store.range_reads == 0


def test_a_corrupt_shard_does_not_abort_the_rest_of_the_level():
    # Two shards along axis 0: the first is corrupt, the second is fine.
    m = meta()
    m["shape"] = [512, 256, 256]
    good, bad = shard_bytes(), shard_bytes(flip=3)

    class Two(FakeStore):
        def get_suffix(self, key, n):
            blob = bad if "/c/0/" in key else good
            return blob[-n:]

    samples = probe_level_volcomp_sharded(
        Two(m, good), "root.zarr", LEVEL, samples_per_level=2,
        inner_per_shard=1)
    statuses = [s.status for s in samples]
    assert statuses.count("index_checksum_mismatch") == 1
    assert statuses.count("missing") == 1


def test_index_without_crc32c_codec_is_reported_unchecksummed_not_verified():
    store = FakeStore(meta(index_codecs=("bytes",)),
                      shard_bytes(with_crc=False))
    samples = probe(store)
    assert [s.status for s in samples] == ["missing"] * 3
    assert {s.index_crc for s in samples} == {"unchecksummed"}


def test_start_located_index_is_refused_not_misread_as_corruption():
    store = FakeStore(meta(index_location="start"), shard_bytes())
    samples = probe(store)
    assert [s.status for s in samples] == ["undecodable"]
    assert "index_location" in samples[0].detail
    # never fetched the shard tail and "verified" garbage
    assert store.suffix_reads == 0


# ---- finding codes and CLI summary ---------------------------------------------

def test_status_table_preserves_historical_codes_and_adds_the_new_one():
    from zpa.scan_empty_chunks import FALLBACK_FINDING, SAMPLE_FINDINGS
    assert SAMPLE_FINDINGS["populated"] == ("CHUNK_SAMPLE_POPULATED", "info")
    assert SAMPLE_FINDINGS["empty"] == ("CHUNK_SAMPLE_EMPTY", "info")
    assert SAMPLE_FINDINGS["missing"] == ("CHUNK_SAMPLE_MISSING", "info")
    assert SAMPLE_FINDINGS["absent"] == ("CHUNK_SAMPLE_ABSENT", "info")
    assert SAMPLE_FINDINGS["undecodable"] == ("CHUNK_UNDECODEABLE", "low")
    assert FALLBACK_FINDING == ("CHUNK_FETCH_ERROR", "low")
    # low until validated on live data: medium maps to CAUTION downstream, and
    # a non-conforming writer would flag every shard
    assert SAMPLE_FINDINGS["index_checksum_mismatch"] == (
        "SHARD_INDEX_CHECKSUM_MISMATCH", "low")


def test_cli_emits_the_finding_and_reports_checksum_coverage(
        tmp_path, monkeypatch):
    import csv
    import json
    import sys

    from zpa import scan_empty_chunks as sec

    levels = tmp_path / "levels.jsonl"
    rec = {"root": "a.zarr", "level": "0", "index": 0, "present": True,
           "shape": SHAPE, "chunks": [256] * 3, "fill_value": 0,
           "compressor": "sharding_indexed", "has_chunks": True}
    levels.write_text(json.dumps(rec) + "\n")

    bad = FakeStore(meta(), shard_bytes(flip=3))
    monkeypatch.setattr(sec, "open_store", lambda base: bad)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "zpa-scan-chunks", "--base", "https://fx.invalid/",
        "--levels-jsonl", str(levels), "--samples-per-level", "1",
        "--workers", "1", "--out-dir", str(out)])
    assert sec.main() == 0

    rows = list(csv.DictReader(open(out / "scan_empty_chunks.findings.csv")))
    assert [(r["code"], r["severity"]) for r in rows] == [
        ("SHARD_INDEX_CHECKSUM_MISMATCH", "low")]
    summary = json.load(open(out / "scan_empty_chunks.summary.json"))
    assert summary["index_crc"] == {"mismatch": 1}
    assert summary["by_code"] == {"SHARD_INDEX_CHECKSUM_MISMATCH": 1}
