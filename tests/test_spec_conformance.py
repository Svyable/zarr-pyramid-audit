"""OME-NGFF spec-conformance checks: version gate, transforms, axes.

Every case is a synthetic pyramid served from an in-memory store; nothing
touches the network. The recurring theme is *conservatism*: untyped axes, an
undeclared version or a pre-0.4 pyramid must never be flagged, and a version
newer than the audit models must disable the checks that would give false
findings rather than report them.
"""
import copy
from types import SimpleNamespace

import pytest

from zpa import audit_pyramid
from zpa.audit_pyramid import INFO_CODES, SEVERITY, audit_one
from zpa.gate import check_one
from zpa.zarrmeta import read_pyramid

NEW_CODES = ("OME_VERSION_UNMODELLED", "TRANSFORM_SCALE_COUNT",
             "TRANSFORM_ARITY", "AXES_INVALID")


class FakeStore:
    """Minimal in-memory store speaking the legacy try_json/list_dir API."""

    def __init__(self, files):
        self.files = files

    def try_json(self, path):
        if path in self.files:
            return copy.deepcopy(self.files[path]), None
        return None, "404 Not Found"

    def list_dir(self, path):
        raise FileNotFoundError(path)

    def head(self, path):
        return SimpleNamespace(exists=False)


def array(shape):
    return {"zarr_format": 2, "shape": shape, "chunks": [32] * len(shape),
            "dtype": "<u1", "fill_value": 0, "compressor": None,
            "order": "C", "dimension_separator": "."}


def scale_tf(*vals):
    return {"type": "scale", "scale": list(vals)}


def dataset(path, *vals):
    return {"path": path, "coordinateTransformations": [scale_tf(*vals)]}


ZYX = [{"name": n, "type": "space"} for n in "zyx"]


def multiscale(**over):
    ms = {"version": "0.4", "axes": copy.deepcopy(ZYX),
          "datasets": [dataset("0", 1, 1, 1), dataset("1", 2, 2, 2)]}
    ms.update(over)
    return ms


def audit(ms=None, *, attrs=None, ndim=3):
    """Audit a two-level pyramid whose multiscales block is `ms`."""
    ms = multiscale() if ms is None else ms
    files = {
        "r/.zgroup": {"zarr_format": 2},
        "r/.zattrs": attrs if attrs is not None else {"multiscales": [ms]},
        "r/0/.zarray": array([64] * ndim),
        "r/1/.zarray": array([32] * ndim),
    }
    pm = read_pyramid(FakeStore(files), "r", probe_extra_levels=0,
                      check_chunks=False)
    return audit_one(pm)


def new_findings(result):
    findings = result[0]
    return [f for f in findings if f["code"] in NEW_CODES]


def codes(result):
    return [f["code"] for f in new_findings(result)]


# ---- registry ---------------------------------------------------------------

def test_new_codes_are_registered_with_conservative_severities():
    assert SEVERITY["OME_VERSION_UNMODELLED"] == "info"
    assert "OME_VERSION_UNMODELLED" in INFO_CODES
    for code in ("TRANSFORM_SCALE_COUNT", "TRANSFORM_ARITY", "AXES_INVALID"):
        # Spec conformance with no corpus evidence behind it: never high.
        assert SEVERITY[code] == "low"
        assert code not in INFO_CODES


# ---- clean pyramids stay clean ---------------------------------------------

def test_clean_v04_pyramid_has_no_new_findings():
    result = audit()
    assert new_findings(result) == []
    assert result[2]["ome_version"] == "0.4"


def test_clean_v05_pyramid_with_ome_wrapper_has_no_new_findings():
    ms = multiscale()
    del ms["version"]
    result = audit(attrs={"ome": {"version": "0.5", "multiscales": [ms]}})
    assert new_findings(result) == []
    assert result[2]["ome_version"] == "0.5"


def test_translation_after_scale_is_accepted():
    ms = multiscale()
    for ds in ms["datasets"]:
        ds["coordinateTransformations"].append(
            {"type": "translation", "translation": [0, 0, 0]})
    assert new_findings(audit(ms)) == []


@pytest.mark.parametrize("axes", [
    [],                                                  # 49 real pyramids
    ["z", "y", "x"],                                     # legacy string axes
    [{"name": n} for n in "zyx"],                        # untyped dict axes
    [{"name": "t", "type": "time"}, {"name": "c", "type": "channel"}]
    + [{"name": n, "type": "space"} for n in "zyx"],     # full tczyx
    [{"name": "c", "type": None}]
    + [{"name": n, "type": "space"} for n in "zyx"],     # null/custom slot
])
def test_conforming_axes_are_never_flagged(axes):
    ndim = len(axes) or 3
    ms = multiscale(axes=axes)
    for ds in ms["datasets"]:
        ds["coordinateTransformations"] = [scale_tf(*([ds["coordinateTransformations"][0]["scale"][0]] * ndim))]
    assert "AXES_INVALID" not in codes(audit(ms, ndim=ndim))


# ---- version gate ------------------------------------------------------------

@pytest.mark.parametrize("version", ["0.6", "0.10", "1.0", "banana", 5, ""])
def test_unmodelled_version_is_flagged_info(version):
    result = audit(multiscale(version=version))
    found = [f for f in new_findings(result)
             if f["code"] == "OME_VERSION_UNMODELLED"]
    assert len(found) == 1
    assert found[0]["severity"] == "info"
    assert found[0]["observed"] == repr(version)


def test_unmodelled_version_suppresses_conformance_checks():
    # A 0.6-style sequence transform has no top-level `scale`, and its axes
    # may follow the newer coordinate-system model. Reporting those as
    # TRANSFORM_SCALE_COUNT / AXES_INVALID would be a false finding.
    ms = multiscale(version="0.6", axes=[{"name": "z"}, {"name": "z"}])
    for ds in ms["datasets"]:
        ds["coordinateTransformations"] = [
            {"type": "sequence", "input": "0", "output": "physical",
             "transformations": [scale_tf(1, 1, 1)]}]
    assert codes(audit(ms)) == ["OME_VERSION_UNMODELLED"]


def test_coordinate_systems_without_version_is_unmodelled():
    ms = multiscale(coordinateSystems=[{"name": "physical", "axes": []}])
    del ms["version"]
    assert "OME_VERSION_UNMODELLED" in codes(audit(ms))


def test_undeclared_version_is_not_flagged():
    ms = multiscale()
    del ms["version"]
    result = audit(ms)
    assert new_findings(result) == []
    assert result[2]["ome_version"] is None


def test_pre_04_pyramid_without_transforms_is_silent():
    ms = multiscale(version="0.3", axes=["z", "y", "x"])
    for ds in ms["datasets"]:
        ds.pop("coordinateTransformations")
    assert new_findings(audit(ms)) == []


def test_undeclared_version_and_no_transforms_anywhere_is_silent():
    ms = multiscale()
    del ms["version"]
    for ds in ms["datasets"]:
        ds.pop("coordinateTransformations")
    assert new_findings(audit(ms)) == []


# ---- TRANSFORM_SCALE_COUNT ------------------------------------------------------

def test_dataset_without_scale_is_flagged_on_that_level():
    ms = multiscale()
    ms["datasets"][1]["coordinateTransformations"] = [
        {"type": "translation", "translation": [0, 0, 0]}]
    found = new_findings(audit(ms))
    assert [(f["code"], f["level"]) for f in found] == [
        ("TRANSFORM_SCALE_COUNT", "1")]
    assert found[0]["severity"] == "low"
    assert found[0]["observed"] == "0"
    assert found[0]["expected"] == "1"


def test_dataset_with_missing_transform_key_is_flagged_when_siblings_have_it():
    ms = multiscale()
    ms["datasets"][1].pop("coordinateTransformations")
    found = new_findings(audit(ms))
    assert [(f["code"], f["level"]) for f in found] == [
        ("TRANSFORM_SCALE_COUNT", "1")]


def test_dataset_with_two_scales_is_flagged():
    ms = multiscale()
    ms["datasets"][0]["coordinateTransformations"].append(scale_tf(1, 1, 1))
    found = new_findings(audit(ms))
    assert [(f["code"], f["level"], f["observed"]) for f in found] == [
        ("TRANSFORM_SCALE_COUNT", "0", "2")]


def test_non_list_coordinate_transformations_counts_as_no_scale():
    ms = multiscale()
    ms["datasets"][0]["coordinateTransformations"] = {"type": "scale"}
    assert codes(audit(ms)) == ["TRANSFORM_SCALE_COUNT"]


# ---- TRANSFORM_ARITY ----------------------------------------------------------

def test_scale_shorter_than_axes_is_flagged():
    ms = multiscale()
    ms["datasets"][1]["coordinateTransformations"] = [scale_tf(2, 2)]
    found = new_findings(audit(ms))
    assert [(f["code"], f["level"]) for f in found] == [
        ("TRANSFORM_ARITY", "1")]
    assert found[0]["observed"] == "2"
    assert found[0]["expected"] == "3"
    assert "scale" in found[0]["detail"]


def test_wrong_length_scale_names_its_root_cause_alongside_shape_mismatch():
    # The pre-existing shape-vs-scale check zips a short scale against the
    # base shape and reports a confusing ceil/floor mismatch. TRANSFORM_ARITY
    # is what tells the reviewer the scale list is simply the wrong length.
    ms = multiscale()
    ms["datasets"][1]["coordinateTransformations"] = [scale_tf(2, 2)]
    all_codes = [f["code"] for f in audit(ms)[0]]
    assert "TRANSFORM_ARITY" in all_codes


def test_translation_of_wrong_length_is_flagged():
    ms = multiscale()
    ms["datasets"][0]["coordinateTransformations"].append(
        {"type": "translation", "translation": [0, 0]})
    found = new_findings(audit(ms))
    assert [(f["code"], f["level"]) for f in found] == [
        ("TRANSFORM_ARITY", "0")]
    assert "translation" in found[0]["detail"]


def test_scale_payload_that_is_not_a_list_is_flagged():
    ms = multiscale()
    ms["datasets"][0]["coordinateTransformations"] = [
        {"type": "scale", "scale": "1,1,1"}]
    assert codes(audit(ms)) == ["TRANSFORM_ARITY"]


def test_arity_falls_back_to_array_ndim_when_no_axes_declared():
    ms = multiscale(axes=[])
    ms["datasets"][1]["coordinateTransformations"] = [scale_tf(2, 2)]
    found = new_findings(audit(ms))
    assert [(f["code"], f["expected"]) for f in found] == [
        ("TRANSFORM_ARITY", "3")]


# ---- AXES_INVALID --------------------------------------------------------------

def test_duplicate_axis_names_are_flagged():
    axes = [{"name": "z", "type": "space"}, {"name": "y", "type": "space"},
            {"name": "y", "type": "space"}]
    found = new_findings(audit(multiscale(axes=axes)))
    assert [f["code"] for f in found] == ["AXES_INVALID"]
    assert "duplicate" in found[0]["detail"] and "y" in found[0]["detail"]


def test_space_axis_after_channel_axis_violates_ordering():
    axes = [{"name": "z", "type": "space"}, {"name": "c", "type": "channel"},
            {"name": "y", "type": "space"}, {"name": "x", "type": "space"}]
    ms = multiscale(axes=axes)
    for ds in ms["datasets"]:
        ds["coordinateTransformations"] = [scale_tf(1, 1, 1, 1)]
    result = audit(ms, ndim=4)
    found = new_findings(result)
    assert [f["code"] for f in found] == ["AXES_INVALID"]
    assert "order" in found[0]["detail"]


def test_time_axis_after_space_axes_violates_ordering():
    axes = [{"name": n, "type": "space"} for n in "yx"] + [
        {"name": "t", "type": "time"}]
    ms = multiscale(axes=axes)
    assert codes(audit(ms)) == ["AXES_INVALID"]


def test_four_space_axes_is_flagged():
    axes = [{"name": n, "type": "space"} for n in "wzyx"]
    ms = multiscale(axes=axes)
    for ds in ms["datasets"]:
        ds["coordinateTransformations"] = [scale_tf(1, 1, 1, 1)]
    found = new_findings(audit(ms, ndim=4))
    assert [f["code"] for f in found] == ["AXES_INVALID"]
    assert "space" in found[0]["detail"]


def test_two_time_axes_is_flagged():
    axes = [{"name": "t", "type": "time"}, {"name": "u", "type": "time"}] + [
        {"name": n, "type": "space"} for n in "yx"]
    ms = multiscale(axes=axes)
    for ds in ms["datasets"]:
        ds["coordinateTransformations"] = [scale_tf(1, 1, 1, 1)]
    assert codes(audit(ms, ndim=4)) == ["AXES_INVALID"]


def test_single_axis_is_outside_the_two_to_five_range():
    ms = multiscale(axes=[{"name": "x", "type": "space"}])
    for ds in ms["datasets"]:
        ds["coordinateTransformations"] = [scale_tf(1)]
    assert "AXES_INVALID" in codes(audit(ms, ndim=1))


def test_axes_findings_are_emitted_once_per_pyramid():
    axes = [{"name": "z", "type": "space"}, {"name": "z", "type": "space"},
            {"name": "x", "type": "space"}]
    assert codes(audit(multiscale(axes=axes))).count("AXES_INVALID") == 1


# ---- interplay with existing checks -----------------------------------------------

def test_existing_axes_mismatch_still_fires_independently():
    result = audit(multiscale(), ndim=2)
    all_codes = [f["code"] for f in result[0]]
    assert "AXES_MISMATCH" in all_codes


def test_new_codes_never_reach_high_severity_in_audit_output():
    ms = multiscale(version="0.6")
    ms["datasets"][0]["coordinateTransformations"] = []
    bad = multiscale(axes=[{"name": "z"}, {"name": "z"}, {"name": "x"}])
    bad["datasets"][0]["coordinateTransformations"] = [scale_tf(1, 1)]
    for result in (audit(ms), audit(bad)):
        for f in new_findings(result):
            assert f["severity"] in ("info", "low")


# ---- publish gate ---------------------------------------------------------------

def _gate(ms, fail_on):
    files = {
        "r/.zgroup": {"zarr_format": 2},
        "r/.zattrs": {"multiscales": [ms]},
        "r/0/.zarray": array([64] * 3),
        "r/1/.zarray": array([32] * 3),
    }
    args = SimpleNamespace(fail_on=fail_on, no_chunk_presence=True,
                           ignore_unreadable=False)
    return check_one(FakeStore(files), "r", args)


def test_conformance_findings_do_not_block_the_default_gate():
    # A wrong-length translation: unlike a wrong-length scale it does not feed
    # the (high) shape-vs-scale check, so this isolates the low finding.
    ms = multiscale()
    ms["datasets"][1]["coordinateTransformations"].append(
        {"type": "translation", "translation": [0, 0]})
    assert _gate(ms, "high")["verdict"] == "pass"
    blocked = _gate(ms, "low")
    assert blocked["verdict"] == "fail"
    assert [f["code"] for f in blocked["findings"]] == ["TRANSFORM_ARITY"]


def test_unmodelled_version_is_informational_at_every_gate_threshold_but_info():
    ms = multiscale(version="0.6")
    for level in ("high", "medium", "low"):
        result = _gate(ms, level)
        assert result["verdict"] == "pass"
        assert [i["code"] for i in result["informational"]] == [
            "OME_VERSION_UNMODELLED"]


# ---- one root cause is reported once ------------------------------------------

def test_axes_that_disagree_with_the_array_do_not_also_blame_every_transform():
    # Two axes declared for 3-D arrays (AXES_MISMATCH). The scales match the
    # arrays, so the axes list is the odd one out: flagging each level's scale
    # as well would report one defect once per level.
    ms = multiscale(axes=ZYX[1:])
    result = audit(ms, ndim=3)
    all_codes = [f["code"] for f in result[0]]
    assert "AXES_MISMATCH" in all_codes
    assert "TRANSFORM_ARITY" not in all_codes


def test_transform_that_matches_neither_axes_nor_array_is_still_flagged():
    ms = multiscale(axes=ZYX[1:])          # axes say 2, array is 3-D
    ms["datasets"][1]["coordinateTransformations"] = [
        {"type": "translation", "translation": [0, 0, 0, 0]}]  # 4: neither
    ms["datasets"][1]["coordinateTransformations"].append(scale_tf(2, 2, 2))
    found = [f for f in audit(ms)[0] if f["code"] == "TRANSFORM_ARITY"]
    assert [f["level"] for f in found] == ["1"]
