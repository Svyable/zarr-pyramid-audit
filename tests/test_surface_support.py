import numpy as np
import pytest

from zpa.surface_support import audit_arrays, count_block, validate_expected_volume_id


class FakeArray:
    def __init__(self, data, chunks):
        self._data = np.asarray(data)
        self.shape = self._data.shape
        self.chunks = chunks

    def __getitem__(self, item):
        return self._data[item]


def test_count_block_counts_only_prediction_positive_outside_ct():
    pred = np.array(
        [
            [[0, 200], [200, 0]],
            [[200, 200], [0, 0]],
        ],
        dtype=np.uint8,
    )
    ct = np.array(
        [
            [[0, 1], [0, 0]],
            [[1, 0], [0, 0]],
        ],
        dtype=np.uint8,
    )

    positives, phantom = count_block(pred, ct, threshold=127)

    assert positives.tolist() == [2, 2]
    assert phantom.tolist() == [1, 1]


def test_audit_arrays_stride_is_deterministic_and_denominator_is_explicit():
    pred = np.zeros((6, 2, 2), dtype=np.uint8)
    ct = np.zeros_like(pred)

    # z chunks are 2 planes. stride=2 visits chunks starting at z=0 and z=4,
    # so planes z=2,3 are deliberately not in the sampled denominator.
    pred[0, 0, 0] = 255
    ct[0, 0, 0] = 1
    pred[1, 0, 0] = 255
    pred[2:4] = 255
    pred[4, 0, 0] = 255
    ct[4, 0, 0] = 1
    pred[5, 0, 0] = 255
    ct[5, 0, 0] = 1

    report = audit_arrays(
        FakeArray(pred, chunks=(2, 2, 2)),
        FakeArray(ct, chunks=(2, 2, 2)),
        slab_stride=2,
        stripe_bytes=1024,
    )

    assert report["planned_slabs"] == 2
    assert report["slabs_measured"] == 2
    assert report["planes_measured"] == 4
    assert [r["z"] for r in report["per_plane"]] == [0, 1, 4, 5]
    assert report["sampled_positives"] == 4
    assert report["sampled_phantom"] == 1
    assert report["sampled_support_frac"] == pytest.approx(0.75)


def test_audit_arrays_fails_on_grid_mismatch():
    pred = FakeArray(np.zeros((2, 2, 2), dtype=np.uint8), chunks=(1, 2, 2))
    ct = FakeArray(np.zeros((3, 2, 2), dtype=np.uint8), chunks=(1, 2, 2))

    with pytest.raises(ValueError, match="grid mismatch"):
        audit_arrays(pred, ct)


def test_audit_arrays_requires_positive_stride():
    arr = FakeArray(np.zeros((2, 2, 2), dtype=np.uint8), chunks=(1, 2, 2))
    with pytest.raises(ValueError, match="slab_stride"):
        audit_arrays(arr, arr, slab_stride=0)


def test_audit_arrays_no_prediction_positives_is_not_perfect_support():
    arr = FakeArray(np.zeros((2, 2, 2), dtype=np.uint8), chunks=(1, 2, 2))
    report = audit_arrays(arr, arr, slab_stride=1, stripe_bytes=1024)

    assert report["sampled_positives"] == 0
    assert report["sampled_phantom_frac"] is None
    assert report["sampled_support_frac"] is None
    assert report["plane_coverage_frac"] == pytest.approx(1.0)
    assert all(r["phantom_frac"] is None for r in report["per_plane"])



def test_expected_volume_id_guard_checks_both_paths():
    validate_expected_volume_id(
        "s3://bucket/PHerc1203/predictions/20250820131727-surface.zarr",
        "s3://bucket/PHerc1203/volumes/20250820131727-9.362um.zarr",
        "20250820131727",
    )

    with pytest.raises(ValueError, match="missing from predictions"):
        validate_expected_volume_id(
            "s3://bucket/PHerc1203/predictions/20260319130212-surface.zarr",
            "s3://bucket/PHerc1203/volumes/20250820131727-9.362um.zarr",
            "20250820131727",
        )

    with pytest.raises(ValueError, match="missing from ct"):
        validate_expected_volume_id(
            "s3://bucket/PHerc1203/predictions/20250820131727-surface.zarr",
            "s3://bucket/PHerc1203/volumes/20260319130212-2.403um.zarr",
            "20250820131727",
        )
