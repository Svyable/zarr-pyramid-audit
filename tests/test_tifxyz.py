"""zpa-tifxyz: tifxyz surface integrity (offline).

The fixture corpus (fixtures/surfaces/, goldens in fixtures/expected/)
pins one property per case. These tests cover what fixtures cannot:
transport failures, TIFF layouts the corpus does not commit (big-endian,
truncated, compressed/tiled), decoder agreement, the CLI and discovery.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import zlib

import numpy as np
import pytest

from zpa import tifxyz as tx
from zpa.httpstore import LocalStore, ObjectInfo, StoreError
from zpa.report import validate_report

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "fixtures"))
import corpus  # noqa: E402

SURF = corpus.SURF_DIR


def copy_case(tmp_path, name="tifxyz_clean"):
    dst = tmp_path / f"{name}.tifxyz"
    shutil.copytree(os.path.join(SURF, f"{name}.tifxyz"), dst)
    return dst


def codes(report):
    return sorted(f["code"] for f in report["findings"])


# ---- evidence semantics -------------------------------------------------------

class FlakyStore(LocalStore):
    """A local store whose reads of one file fail like a 503."""

    def __init__(self, base, failing):
        super().__init__(base)
        self.failing = failing

    def head(self, path):
        if path.endswith(self.failing):
            return ObjectInfo(path=path, exists=False, status=503,
                              error="HTTP 503")
        return super().head(path)

    def get(self, path):
        if path.endswith(self.failing):
            raise StoreError("HTTP 503: " + path)
        return super().get(path)


def test_unreadable_channel_is_unknown_never_missing():
    report = tx.audit_surface(FlakyStore(SURF, "z.tif"), "tifxyz_clean.tifxyz",
                              content=True)
    assert codes(report) == ["ACCESS_UNKNOWN"]
    assert report["findings"][0]["evidence_state"] == "UNKNOWN"
    assert report["integrity"] == "UNKNOWN"
    assert report["surface"]["content_checked"] is False


def test_unreadable_meta_is_unknown_never_missing():
    report = tx.audit_surface(FlakyStore(SURF, "meta.json"),
                              "tifxyz_clean.tifxyz")
    assert codes(report) == ["ACCESS_UNKNOWN"]
    assert report["integrity"] == "UNKNOWN"


def test_header_tier_reads_a_few_hundred_bytes_per_channel():
    class Counting(LocalStore):
        ranged = 0
        full = 0
        _inside_range = False

        def get_range(self, path, start, length):
            Counting.ranged += length
            Counting._inside_range = True     # LocalStore slices via get()
            try:
                return super().get_range(path, start, length)
            finally:
                Counting._inside_range = False

        def get(self, path):
            if path.endswith(".tif") and not Counting._inside_range:
                Counting.full += 1
            return super().get(path)

    report = tx.audit_surface(Counting(SURF), "tifxyz_clean.tifxyz")
    assert report["integrity"] == "PASS"
    assert Counting.full == 0                # no channel read in full
    assert Counting.ranged < 3 * 512         # header + IFD only


# ---- TIFF parsing -------------------------------------------------------------

def _big_endian_tiff(path, arr):
    arr = arr.astype(">f4")
    data = arr.tobytes()
    h, w = arr.shape
    entries = [(256, 3, w), (257, 3, h), (258, 3, 32), (259, 3, 1),
               (273, 4, 8), (277, 3, 1), (278, 3, h), (279, 4, len(data)),
               (339, 3, 3)]
    ifd_off = 8 + len(data)
    out = struct.pack(">2sHI", b"MM", 42, ifd_off) + data
    out += struct.pack(">H", len(entries))
    for tag, typ, val in entries:
        out += (struct.pack(">HHIH2x", tag, typ, 1, val) if typ == 3
                else struct.pack(">HHII", tag, typ, 1, val))
    out += struct.pack(">I", 0)
    path.write_bytes(out)


def test_big_endian_tiff_parses_and_decodes(tmp_path):
    d = copy_case(tmp_path)
    x, y, z = corpus._surface_xyz()
    for name, arr in zip("xyz", (x, y, z)):
        _big_endian_tiff(d / f"{name}.tif", arr)
    report = tx.audit_surface(LocalStore(tmp_path), d.name, content=True)
    assert report["findings"] == []
    assert report["surface"]["decoders"] == {"x": "builtin", "y": "builtin",
                                             "z": "builtin"}
    assert report["surface"]["valid_fraction"] == pytest.approx(46 / 48)


def test_truncated_ifd_is_unreadable_not_a_crash(tmp_path):
    d = copy_case(tmp_path)
    blob = (d / "x.tif").read_bytes()
    (d / "x.tif").write_bytes(blob[:-20])      # cut into the IFD
    report = tx.audit_surface(LocalStore(tmp_path), d.name, content=True)
    assert codes(report) == ["TIFXYZ_TIFF_UNREADABLE"]
    assert report["findings"][0]["level"] == "x.tif"


# ---- decoders -----------------------------------------------------------------

def _deflate_predictor_tiff(path, arr):
    """Deflate + floating-point predictor: not decoded by the built-in path."""
    arr = arr.astype("<f4")
    data = zlib.compress(arr.tobytes())
    h, w = arr.shape
    entries = [(256, 3, w), (257, 3, h), (258, 3, 32), (259, 3, 8),
               (273, 4, 8), (277, 3, 1), (278, 3, h), (279, 4, len(data)),
               (317, 3, 3), (339, 3, 3)]
    ifd_off = 8 + len(data)
    out = struct.pack("<2sHI", b"II", 42, ifd_off) + data
    out += struct.pack("<H", len(entries))
    for tag, typ, val in entries:
        out += (struct.pack("<HHIH2x", tag, typ, 1, val) if typ == 3
                else struct.pack("<HHII", tag, typ, 1, val))
    out += struct.pack("<I", 0)
    path.write_bytes(out)


def test_undecodable_layout_is_a_coverage_gap_not_a_finding(tmp_path, monkeypatch):
    d = copy_case(tmp_path)
    x, _, _ = corpus._surface_xyz()
    _deflate_predictor_tiff(d / "x.tif", x)
    monkeypatch.setattr(tx, "_tifffile_decode", lambda blob: None)
    report = tx.audit_surface(LocalStore(tmp_path), d.name, content=True)
    assert codes(report) == ["TIFXYZ_CONTENT_UNDECODED"]
    assert report["findings"][0]["severity"] == "info"
    assert report["surface"]["content_checked"] is False
    assert report["integrity"] == "PASS"   # header evidence is complete
    assert validate_report(report) == []


def test_builtin_and_tifffile_decoders_agree():
    tifffile = pytest.importorskip("tifffile")  # noqa: F841
    for name in ("tifxyz_clean", "tifxyz_bigtiff_clean"):
        for ch in "xyz":
            path = os.path.join(SURF, f"{name}.tifxyz", f"{ch}.tif")
            blob = open(path, "rb").read()
            store = LocalStore(SURF)
            hdr = tx.parse_tiff_header(store, f"{name}.tifxyz/{ch}.tif", len(blob))
            a = tx.decode_channel(blob, hdr)
            b = tx._tifffile_decode(blob)
            assert a is not None and b is not None
            assert np.array_equal(a, b), (name, ch)


def test_tiled_lzw_surface_decodes_through_tifffile(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    pytest.importorskip("imagecodecs")
    d = copy_case(tmp_path)
    for name, arr in zip("xyz", corpus._surface_xyz()):
        tifffile.imwrite(d / f"{name}.tif", arr, tile=(16, 16),
                         compression="lzw", predictor=True)
    report = tx.audit_surface(LocalStore(tmp_path), d.name, content=True)
    assert report["findings"] == []
    assert report["surface"]["decoders"] == {"x": "tifffile", "y": "tifffile",
                                             "z": "tifffile"}
    golden = json.load(open(os.path.join(corpus.EXPECTED_DIR, "tifxyz_clean.json")))
    assert report["surface"]["data_bbox"] == golden["surface"]["data_bbox"]


# ---- CLI ----------------------------------------------------------------------

def run_cli(tmp_path, *extra, roots=("tifxyz_clean.tifxyz",)):
    out = tmp_path / "out"
    argv = ["--base", SURF, "--workers", "1", "--out-dir", str(out), *extra]
    for r in roots:
        argv += ["--root", r]
    return tx.main(argv), out


def test_cli_writes_reports_and_findings(tmp_path):
    code, out = run_cli(tmp_path, "--content",
                        roots=("tifxyz_clean.tifxyz", "tifxyz_empty.tifxyz"))
    assert code == 0
    reports = [json.loads(l) for l in open(out / "tifxyz.reports.jsonl")]
    assert {r["root"]: r["integrity"] for r in reports} == {
        "tifxyz_clean.tifxyz": "PASS", "tifxyz_empty.tifxyz": "WARN"}
    assert all(validate_report(r) == [] for r in reports)
    summary = json.load(open(out / "tifxyz.summary.json"))
    assert summary["by_code"] == {"TIFXYZ_EMPTY": 1}
    assert summary["content_checked"] == 2


def test_cli_gate_mode_fails_closed(tmp_path):
    assert run_cli(tmp_path, "--content", "--fail-on", "medium",
                   roots=("tifxyz_empty.tifxyz",))[0] == 1
    assert run_cli(tmp_path, "--fail-on", "medium",
                   roots=("tifxyz_absent.tifxyz",))[0] == 1   # UNKNOWN fails
    assert run_cli(tmp_path, "--content", "--fail-on", "medium")[0] == 0


# ---- discovery ----------------------------------------------------------------

def test_discover_records_tifxyz_surfaces_without_entering_them(tmp_path, monkeypatch):
    seg = tmp_path / "PHercX" / "segments" / "s1" / "mesh"
    shutil.copytree(os.path.join(SURF, "tifxyz_clean.tifxyz"), seg / "a.tifxyz")
    shutil.copytree(os.path.join(SURF, "tifxyz_clean.tifxyz"),
                    seg / "intermediate" / "tifxyz_original")
    out = tmp_path / "out"
    from zpa import discover_zarr
    monkeypatch.setattr(sys, "argv", ["zpa-discover", "--base", str(tmp_path),
                                      "--max-depth", "10", "--workers", "1",
                                      "--out-dir", str(out)])
    assert discover_zarr.main() == 0
    rows = [json.loads(l) for l in open(out / "discover_zarr.surfaces.jsonl")]
    found = {r["root"]: r["detected_by"] for r in rows}
    assert found == {
        "PHercX/segments/s1/mesh/a.tifxyz": "name",
        "PHercX/segments/s1/mesh/intermediate/tifxyz_original": "files",
    }
    listed = [json.loads(l)["path"] for l in open(out / "discover_zarr.dirs.jsonl")]
    assert "PHercX/segments/s1/mesh/a.tifxyz" not in listed   # rule 4 still prunes


def test_readme_tifxyz_code_table_matches_the_code():
    import re
    text = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
    section = text.split("### tifxyz surface codes", 1)[1].split("\n\n", 2)[1]
    listed = dict(re.findall(r"^\| `([A-Z_]+)` \| (\w+) \|", section, re.M))
    assert listed == tx.TIFXYZ_SEVERITY
