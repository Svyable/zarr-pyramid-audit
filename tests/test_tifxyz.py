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


def test_vc3d_target_context_is_preserved_in_report(tmp_path):
    d = copy_case(tmp_path)
    meta_path = d / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({
        "source": "vc_grow_seg_from_seed",
        "target_volume": "20250821151723.zarr",
        "scroll_source": "PHerc0813",
        "vc_gsfs_mode": "seed",
        "vc_gsfs_version": "dev",
    })
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    report = tx.audit_surface(LocalStore(tmp_path), d.name)

    assert report["integrity"] == "PASS"
    assert report["surface"]["meta"]["source"] == "vc_grow_seg_from_seed"
    assert report["surface"]["meta"]["target_volume"] == "20250821151723.zarr"
    assert report["surface"]["meta"]["scroll_source"] == "PHerc0813"
    assert report["surface"]["meta"]["vc_gsfs_mode"] == "seed"
    assert report["surface"]["meta"]["vc_gsfs_version"] == "dev"
    assert validate_report(report) == []


def test_expected_target_volume_guard_accepts_exact_id_path_and_zarr_name(tmp_path):
    d = copy_case(tmp_path)
    meta_path = d / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["target_volume"] = "s3://bucket/PHerc0813/volumes/20250821151723.zarr"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    store = LocalStore(tmp_path)

    for expected in (
        "20250821151723",
        "20250821151723.zarr",
        "s3://other-bucket/volumes/20250821151723.zarr",
    ):
        tx.validate_expected_target_volume(store, [d.name], expected)


def test_expected_target_volume_guard_rejects_wrong_or_missing_target(tmp_path):
    d = copy_case(tmp_path)
    store = LocalStore(tmp_path)

    with pytest.raises(ValueError, match="target_volume"):
        tx.validate_expected_target_volume(
            store, [d.name], "20250821151723"
        )

    meta_path = d / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["target_volume"] = "20250821151724.zarr"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="20250821151724"):
        tx.validate_expected_target_volume(
            store, [d.name], "20250821151723"
        )


def test_cli_expected_target_guard_fails_before_report_outputs(tmp_path):
    d = copy_case(tmp_path)
    meta_path = d / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["target_volume"] = "wrong-volume.zarr"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    out = tmp_path / "guarded-out"

    code = tx.main([
        "--base", str(tmp_path),
        "--root", d.name,
        "--workers", "1",
        "--expected-target-volume", "20250821151723",
        "--out-dir", str(out),
    ])

    assert code == 2
    assert not (out / "tifxyz.reports.jsonl").exists()
    assert not (out / "tifxyz.summary.json").exists()


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


def test_size_cap_is_checked_before_any_channel_is_downloaded():
    class NoGet(LocalStore):
        def get(self, path):
            if path.endswith(".tif") and not getattr(self, "_ranged", False):
                raise AssertionError(f"downloaded {path} despite the size cap")
            return super().get(path)

        def get_range(self, path, start, length):
            self._ranged = True
            try:
                return super().get_range(path, start, length)
            finally:
                self._ranged = False

    report = tx.audit_surface(NoGet(SURF), "tifxyz_clean.tifxyz", content=True,
                              max_content_bytes=10)
    assert codes(report) == ["TIFXYZ_CONTENT_UNDECODED"]
    assert report["surface"]["content_checked"] is False


def test_exact_target_shape_flags_upper_bound_overrun_from_clean_fixture():
    """Existing clean TIFXYZ becomes an overrun under a smaller exact CT grid."""
    report = tx.audit_surface(
        LocalStore(SURF),
        "tifxyz_clean.tifxyz",
        content=True,
        target_shape_zyx=(400, 400, 112),
    )

    assert report["surface"]["target_shape_zyx"] == [400, 400, 112]
    assert report["surface"]["target_overrun_points"] == 11
    finding = next(
        f for f in report["findings"]
        if f["code"] == "TIFXYZ_TARGET_VOLUME_OVERRUN"
    )
    assert finding["severity"] == "low"
    assert finding["observed"] == "11"
    assert finding["expected"] == "0"
    assert "x" in finding["detail"]
    assert validate_report(report) == []

    golden_path = os.path.join(REPO, "fixtures", "tifxyz-target-bounds.expected.json")
    with open(golden_path, encoding="utf-8") as handle:
        golden = json.load(handle)
    assert {
        "target_shape_zyx": report["surface"]["target_shape_zyx"],
        "target_overrun_points": report["surface"]["target_overrun_points"],
        "finding": {
            key: finding[key]
            for key in ("code", "severity", "evidence_state", "actionable")
        },
    } == golden


def test_exact_target_shape_clean_when_all_points_fit():
    report = tx.audit_surface(
        LocalStore(SURF),
        "tifxyz_clean.tifxyz",
        content=True,
        target_shape_zyx=(400, 400, 400),
    )
    assert report["surface"]["target_overrun_points"] == 0
    assert "TIFXYZ_TARGET_VOLUME_OVERRUN" not in codes(report)


def test_target_shape_validation_is_fail_closed():
    with pytest.raises(ValueError, match="three positive integers"):
        tx.audit_surface(
            LocalStore(SURF),
            "tifxyz_clean.tifxyz",
            content=True,
            target_shape_zyx=(400, 0, 400),
        )


def test_cli_requires_target_volume_identity_when_shape_is_supplied(tmp_path, capsys):
    rc = tx.main([
        "--base", SURF,
        "--root", "tifxyz_clean.tifxyz",
        "--content",
        "--target-shape-zyx", "400", "400", "112",
        "--out-dir", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "--target-shape-zyx requires --expected-target-volume" in capsys.readouterr().err
