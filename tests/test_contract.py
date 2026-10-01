"""The downstream contract: schema, severities, integrity states, verdicts.

ScrolIQ (and any training pipeline) branches on these values, so they are
an API. A change here must be deliberate: update the schema, the fixture
goldens and CHANGELOG.md (see "Contract changes" there).
"""
from __future__ import annotations

import inspect
import itertools
import json
import os

import pytest

from zpa import report as rpt
from zpa.audit_pyramid import INFO_CODES, SEVERITY, audit_one
from zpa.chunkscan import SCAN_SEVERITY
from zpa.httpstore import open_store
from zpa.zarrmeta import read_pyramid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def f(code, severity, evidence="PRESENT"):
    return {"code": code, "severity": severity, "level": "", "detail": "",
            "evidence_state": evidence}


# ---- severity x evidence -> integrity -> recommended consumer verdict ------

VERDICT_TABLE = [
    # findings                                              integrity  verdict
    ([],                                                     "PASS",    "DEFER_TO_QUALITY"),
    ([f("BARE_ARRAY", "info")],                              "PASS",    "DEFER_TO_QUALITY"),
    ([f("COMPRESSOR_DRIFT", "low")],                         "PASS",    "DEFER_TO_QUALITY"),
    ([f("FILL_DRIFT", "medium")],                            "WARN",    "CAUTION"),
    ([f("LEVEL_NO_CHUNKS", "high", "ABSENT")],               "FAIL",    "DO NOT TRAIN"),
    ([f("ACCESS_UNKNOWN", "info", "UNKNOWN")],               "UNKNOWN", "DO NOT TRAIN"),
    ([f("ACCESS_UNKNOWN", "info", "UNKNOWN"),
      f("FILL_DRIFT", "medium")],                            "UNKNOWN", "DO NOT TRAIN"),
    ([f("ACCESS_UNKNOWN", "info", "UNKNOWN"),
      f("LEVEL_MISSING", "high", "ABSENT")],                 "FAIL",    "DO NOT TRAIN"),
    ([f("GATE_UNREADABLE", "high", "UNKNOWN")],              "FAIL",    "DO NOT TRAIN"),
    ([f("ROOT_ABSENT", "low", "ABSENT")],                    "UNKNOWN", "DO NOT TRAIN"),
    ([f("EMPTY_ZARR_DIR", "low", "ABSENT")],                 "UNKNOWN", "DO NOT TRAIN"),
]


@pytest.mark.parametrize("findings,integrity,verdict", VERDICT_TABLE)
def test_severity_and_evidence_map_to_verdict(findings, integrity, verdict):
    assert rpt.integrity_of(findings) == integrity
    assert rpt.consumer_verdict({"integrity": integrity}) == verdict


def test_recommended_verdicts_are_pinned():
    assert rpt.RECOMMENDED_CONSUMER_VERDICT == {
        "FAIL": "DO NOT TRAIN", "UNKNOWN": "DO NOT TRAIN",
        "WARN": "CAUTION", "PASS": "DEFER_TO_QUALITY"}


def test_unknown_evidence_never_yields_pass_for_any_combination():
    pool = [f("ACCESS_UNKNOWN", "info", "UNKNOWN")] + [
        f("X", sev, ev) for sev in ("info", "low", "medium", "high")
        for ev in ("PRESENT", "ABSENT", "UNKNOWN")]
    for n in range(1, 4):
        for combo in itertools.combinations(pool, n):
            combo = list(combo)
            if any(x["evidence_state"] == "UNKNOWN" for x in combo):
                state = rpt.integrity_of(combo)
                assert state in ("UNKNOWN", "FAIL"), combo
                assert rpt.consumer_verdict({"integrity": state}) == "DO NOT TRAIN"


def test_high_severity_always_means_do_not_train():
    for code, sev in SEVERITY.items():
        state = rpt.integrity_of([f(code, sev)])
        if sev == "high":
            assert rpt.consumer_verdict({"integrity": state}) == "DO NOT TRAIN", code
        if sev == "medium":
            assert state == "WARN", code


# ---- schema ----------------------------------------------------------------

def test_schema_version_and_codes_match_the_code():
    schema = rpt.load_schema()
    assert schema["properties"]["schema_version"]["const"] == rpt.SCHEMA_VERSION
    assert set(schema["$defs"]["check_code"]["enum"]) == (
        set(SEVERITY) | set(rpt.GATE_SEVERITY))
    assert schema["properties"]["integrity"]["enum"] == list(rpt.INTEGRITY_STATES)


def test_schema_is_shipped_with_the_package():
    from importlib.resources import files
    assert files("zpa").joinpath("data", "audit-report.schema.json").is_file()


def test_validator_rejects_contract_violations():
    good = rpt.audit_root(open_store(os.path.join(REPO, "fixtures", "zarr")),
                          "clean_v2.zarr")
    assert rpt.validate_report(good) == []
    bad = json.loads(json.dumps(good))
    bad["integrity"] = "OK"
    bad["findings"] = [{"code": "MADE_UP"}]
    errors = rpt.validate_report(bad)
    assert any("integrity" in e for e in errors)
    assert any("MADE_UP" in e for e in errors)
    assert any("missing required 'severity'" in e for e in errors)


# ---- public API surface ScrolIQ imports ------------------------------------

def test_public_signatures_scroliq_depends_on():
    assert list(inspect.signature(open_store).parameters) == ["base_url", "kw"]
    params = inspect.signature(read_pyramid).parameters
    assert list(params)[:2] == ["store", "root"]
    assert list(inspect.signature(audit_one).parameters) == ["pm"]


def test_finding_fields_scroliq_reads_are_stable():
    pm = read_pyramid(open_store(os.path.join(REPO, "fixtures", "zarr")),
                      "missing_level.zarr")
    findings, levels, record = audit_one(pm)
    for finding in findings:
        assert {"code", "severity", "level", "detail"} <= set(finding)
    assert "n_levels" in record


def test_audit_root_never_reports_a_crash_as_clean():
    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    report = rpt.audit_root(Exploding(), "root")
    assert report["integrity"] == "FAIL"
    assert report["findings"][0]["code"] == "AUDIT_ERROR"
    assert rpt.validate_report(report) == []


# ---- changelog rule ---------------------------------------------------------

def test_contract_changes_carry_a_migration_note():
    """Adding/changing a check code, a severity, the schema version or the
    verdict mapping changes the fingerprint. Write a migration note in
    CHANGELOG.md that quotes the new fingerprint, and regenerate the
    fixture goldens (python fixtures/corpus.py expected)."""
    fp = rpt.contract_fingerprint()
    with open(os.path.join(REPO, "CHANGELOG.md"), encoding="utf-8") as fh:
        text = fh.read()
    assert f"contract-fingerprint: {fp}" in text, (
        f"contract changed: add a migration note to CHANGELOG.md containing "
        f"'contract-fingerprint: {fp}'")


def test_contract_document_is_complete():
    c = rpt.contract()
    assert c["audit_codes"] == dict(sorted(SEVERITY.items()))
    assert c["chunk_scan_codes"] == dict(sorted(SCAN_SEVERITY.items()))
    assert set(c["info_codes"]) == INFO_CODES
