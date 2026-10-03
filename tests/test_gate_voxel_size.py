from zpa.gate import _check_expected_voxel_size


def _record(scale=(9.362, 9.362, 9.362), units=("micrometer",) * 3):
    return {
        "physical_scale": {
            "physical_size_marker": None,
            "base_declared_scale": list(scale),
            "spatial_axes": [
                {"index": i, "name": name, "unit": unit}
                for i, (name, unit) in enumerate(zip(("z", "y", "x"), units))
            ],
        }
    }


def test_expected_voxel_size_matches_all_spatial_axes():
    evidence, finding = _check_expected_voxel_size(_record(), 9.362, 0.001)

    assert finding is None
    assert evidence["status"] == "match"
    assert [axis["micrometers"] for axis in evidence["axes"]] == [9.362] * 3


def test_expected_voxel_size_converts_declared_units():
    evidence, finding = _check_expected_voxel_size(
        _record(scale=(9362, 9362, 9362), units=("nm",) * 3),
        9.362,
        0.001,
    )

    assert finding is None
    assert evidence["status"] == "match"


def test_expected_voxel_size_mismatch_fails_closed():
    evidence, finding = _check_expected_voxel_size(
        _record(scale=(9.362, 9.362, 2.403)),
        9.362,
        0.001,
    )

    assert evidence["status"] == "mismatch"
    assert finding["code"] == "GATE_VOXEL_SIZE_MISMATCH"
    assert finding["severity"] == "high"
    assert "x=2.403 µm" in finding["detail"]


def test_expected_voxel_size_unknown_unit_fails_closed():
    evidence, finding = _check_expected_voxel_size(
        _record(units=("micrometer", "micrometer", None)),
        9.362,
        0.001,
    )

    assert evidence["status"] == "unknown"
    assert finding["code"] == "GATE_VOXEL_SIZE_UNKNOWN"


def test_expected_voxel_size_respects_explicit_unknown_marker():
    record = _record()
    record["physical_scale"]["physical_size_marker"] = "unknown"

    evidence, finding = _check_expected_voxel_size(record, 9.362, 0.001)

    assert evidence["status"] == "unknown"
    assert finding["code"] == "GATE_VOXEL_SIZE_UNKNOWN"
