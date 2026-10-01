import numpy as np
import pytest

from zpa.surface_depth_profile import (
    _tile_starts,
    profile_surface_volume,
    validate_volume_lineage,
)


class Array:
    def __init__(self, data, chunks=(1, 4, 4)):
        self.data = np.asarray(data)
        self.shape = self.data.shape
        self.chunks = chunks

    def __getitem__(self, item):
        return self.data[item]


def test_tile_starts_are_deterministic_and_bounded():
    assert _tile_starts(100, 20, 3) == [0, 40, 80]
    assert _tile_starts(10, 20, 3) == [0]


def test_profile_finds_zero_and_duplicate_sampled_depths():
    data = np.zeros((4, 8, 8), dtype=np.uint8)
    data[1] = np.arange(64, dtype=np.uint8).reshape(8, 8)
    data[2] = data[1]
    data[3] = np.flipud(data[1])

    report = profile_surface_volume(
        Array(data), grid=2, tile_size=4, expected_depth=4
    )

    assert report["expected_depth_ok"] is True
    assert 0 in report["all_zero_sampled_depths"]
    assert [1, 2] in report["duplicate_sample_digest_depth_groups"]
    assert report["peak_gradient_depth_index"] in {1, 2, 3}


def test_expected_depth_mismatch_is_evidence():
    data = np.ones((3, 4, 4), dtype=np.uint8)
    report = profile_surface_volume(
        Array(data), grid=1, tile_size=4, expected_depth=21
    )
    assert report["expected_depth_ok"] is False
    assert report["shape"] == [3, 4, 4]


def test_source_volume_guard_matches_exactly():
    validate_volume_lineage("eligible-volume", "eligible-volume")
    with pytest.raises(ValueError, match="does not match"):
        validate_volume_lineage("other-volume", "eligible-volume")


def test_depth_percentiles_use_full_sampled_pixel_set():
    data = np.arange(16, dtype=np.float32).reshape(1, 4, 4)
    report = profile_surface_volume(
        Array(data), grid=2, tile_size=2, expected_depth=1
    )
    row = report["per_depth"][0]

    assert row["p01"] == pytest.approx(0.15)
    assert row["p50"] == pytest.approx(7.5)
    assert row["p99"] == pytest.approx(14.85)
