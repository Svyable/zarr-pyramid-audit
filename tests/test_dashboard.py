"""The dashboard generator must not drift from the audit module it describes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from zpa import audit_pyramid, build_dashboard

REPO = Path(__file__).resolve().parents[1]


def test_dashboard_severity_table_matches_audit_module():
    # build_dashboard duplicates the table so Pages CI runs on a bare Python;
    # this test is what keeps the copy honest.
    assert build_dashboard.SEVERITY == audit_pyramid.SEVERITY


def test_every_check_code_has_a_dashboard_blurb():
    missing = sorted(set(build_dashboard.SEVERITY) - set(build_dashboard.CODE_BLURB))
    assert not missing, f"codes without a dashboard blurb: {missing}"


@pytest.fixture
def page(tmp_path, monkeypatch) -> str:
    out = tmp_path / "index.html"
    monkeypatch.setattr(build_dashboard, "REPO", str(REPO))
    monkeypatch.setattr(build_dashboard, "ART", str(REPO / "artifacts"))
    monkeypatch.setattr(sys, "argv", ["zpa-dashboard", "--out", str(out)])
    assert build_dashboard.main() == 0
    return out.read_text(encoding="utf-8")


def test_dashboard_reports_the_real_check_code_count(page):
    n = len(audit_pyramid.SEVERITY)
    assert f"{n} check codes" in page
    assert "24 check codes" not in page


def test_dashboard_explains_the_scroliq_relationship(page):
    assert 'id="scroliq"' in page
    assert 'href="#scroliq"' in page  # nav pill and hero chip
    assert "https://github.com/Svyable/scrollq" in page
    assert "https://svyable.github.io/scrollq/" in page
    for verdict in ("TRAIN", "CAUTION", "DO NOT TRAIN"):
        assert verdict in page
    # The legacy brand may only appear in the naming note, not as the product name.
    assert page.count("ScrollQ") == 1
