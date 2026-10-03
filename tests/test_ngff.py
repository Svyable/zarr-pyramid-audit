"""Optional OME-NGFF conformance (zpa.ngff): reported alongside integrity,
never folded into it, and never ``conforms`` without a validator verdict."""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

from zpa import ngff
from zpa import report as rpt
from zpa.gate import check_one, parse_args
from zpa.httpstore import open_store

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZARR = os.path.join(REPO, "fixtures", "zarr")


def fake_yaozarrs(monkeypatch, exc=None):
    mod = types.ModuleType("yaozarrs")
    mod.__version__ = "0.0-test"
    calls = []

    def validate_zarr_store(uri):
        calls.append(uri)
        if exc is not None:
            raise exc
    mod.validate_zarr_store = validate_zarr_store
    monkeypatch.setitem(sys.modules, "yaozarrs", mod)
    return calls


def test_missing_validator_is_not_checked(monkeypatch):
    monkeypatch.setitem(sys.modules, "yaozarrs", None)   # import fails
    got = ngff.check_ngff("anything")
    assert got["state"] == "not_checked"
    assert "zarr-pyramid-audit[ngff]" in got["detail"]


@pytest.mark.parametrize("exc, state", [
    (None, "conforms"),
    (ValueError("1 validation error for Image"), "nonconformant"),
    (json.JSONDecodeError("Expecting value", "{", 0), "nonconformant"),
    (FileNotFoundError("no zarr.json"), "nonconformant"),
    (NotImplementedError("version 0.6 is not implemented"), "unknown"),
    (TimeoutError("read timed out"), "unknown"),
    (PermissionError("403"), "unknown"),
    (RuntimeError("boom"), "unknown"),
])
def test_validator_outcomes_map_to_states(monkeypatch, exc, state):
    fake_yaozarrs(monkeypatch, exc)
    got = ngff.check_ngff("uri")
    assert got["state"] == state
    assert got["validator"] == "yaozarrs"
    assert got["validator_version"] == "0.0-test"


def test_uri_for_each_store_kind():
    class S3:
        base_url = "s3://bucket/a b/"
        endpoint_url = "https://s3.us-east-1.amazonaws.com"
    assert ngff.ngff_uri(S3(), "/x.zarr/") == (
        "https://s3.us-east-1.amazonaws.com/bucket/a%20b/x.zarr")

    class S3Global:
        base_url = "s3://bucket/"
        endpoint_url = None
    assert ngff.ngff_uri(S3Global(), "x.zarr") == (
        "https://s3.amazonaws.com/bucket/x.zarr")
    assert ngff.ngff_uri(open_store("https://example.org/data"), "x.zarr") == (
        "https://example.org/data/x.zarr")
    local = ngff.ngff_uri(open_store(ZARR), "clean_v2.zarr")
    assert local.startswith("file://") and local.endswith("/clean_v2.zarr")


def test_default_report_says_not_checked():
    report = rpt.audit_root(open_store(ZARR), "clean_v2.zarr")
    assert report["ngff_conformance"]["state"] == "not_checked"
    assert rpt.validate_report(report) == []


def test_nonconformance_never_changes_integrity(monkeypatch):
    store = open_store(ZARR)
    base = rpt.audit_root(store, "clean_v2.zarr")
    fake_yaozarrs(monkeypatch, ValueError("rejected"))
    checked = rpt.audit_root(store, "clean_v2.zarr", ngff=True)
    assert checked["ngff_conformance"]["state"] == "nonconformant"
    assert rpt.validate_report(checked) == []
    for key in ("integrity", "max_severity", "findings", "coverage"):
        assert checked[key] == base[key]


def test_conformance_never_rescues_a_defect(monkeypatch):
    fake_yaozarrs(monkeypatch)                     # validator accepts all
    report = rpt.audit_root(open_store(ZARR), "level_no_chunks.zarr",
                            ngff=True)
    assert report["ngff_conformance"]["state"] == "conforms"
    assert report["integrity"] == "FAIL"


def test_gate_flag_records_but_does_not_decide(monkeypatch, capsys):
    calls = fake_yaozarrs(monkeypatch, ValueError("rejected"))
    store = open_store(ZARR)
    args = parse_args(["--base", ZARR, "--root", "clean_v2.zarr", "--ngff"])
    res = check_one(store, "clean_v2.zarr", args)
    assert res["verdict"] == "pass" and not res["fail"]
    assert res["report"]["ngff_conformance"]["state"] == "nonconformant"
    assert calls and calls[0].endswith("/clean_v2.zarr")

    off = check_one(store, "clean_v2.zarr",
                    parse_args(["--base", ZARR, "--root", "clean_v2.zarr"]))
    assert off["report"]["ngff_conformance"]["state"] == "not_checked"
    assert len(calls) == 1                         # not called without --ngff


def test_audit_error_report_carries_the_field():
    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("boom")
    report = rpt.audit_root(Exploding(), "root", ngff=True)
    assert report["integrity"] == "FAIL"
    assert report["ngff_conformance"]["state"] == "not_checked"
    assert rpt.validate_report(report) == []


def test_contract_lists_the_states():
    assert rpt.contract()["ngff_conformance_states"] == list(ngff.NGFF_STATES)
    schema = rpt.load_schema()
    enum = schema["properties"]["ngff_conformance"]["properties"]["state"]["enum"]
    assert enum == list(ngff.NGFF_STATES)


# ---- with the real validator (skipped unless the [ngff] extra is installed)

@pytest.mark.parametrize("case, state, integrity", [
    ("clean_v2", "conforms", "PASS"),
    ("clean_v3", "conforms", "PASS"),
    ("missing_level", "nonconformant", "FAIL"),
    ("level_no_chunks", "conforms", "FAIL"),     # spec-valid, chunkless
    ("transform_arity", "nonconformant", "PASS"),  # low here, spec error there
])
def test_real_yaozarrs_on_fixtures(case, state, integrity):
    pytest.importorskip("yaozarrs")
    report = rpt.audit_root(open_store(ZARR), f"{case}.zarr", ngff=True)
    assert report["ngff_conformance"]["state"] == state
    assert report["integrity"] == integrity
