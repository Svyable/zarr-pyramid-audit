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


def test_tifxyz_panel_reads_the_committed_summary(tmp_path):
    import json
    summary = {"surfaces": 7, "by_integrity": {"PASS": 6, "WARN": 1},
               "by_code": {"TIFXYZ_EMPTY": 1, "TIFXYZ_CONTENT_UNDECODED": 2},
               "by_severity": {"medium": 1, "info": 2}}
    p = tmp_path / "tifxyz.summary.json"
    p.write_text(json.dumps(summary))
    panel = build_dashboard.render_tifxyz_panel(str(p))
    assert "<b>7</b> surfaces audited" in panel
    assert "<b>6</b> integrity PASS" in panel and "1 WARN" in panel
    assert "medium or above: <b>1</b>" in panel
    assert "skipped on 2 surfaces" in panel
    assert build_dashboard.render_tifxyz_panel(str(tmp_path / "absent.json")) == ""


def test_baseline_panel_reads_the_committed_comparison(page, tmp_path):
    import json
    comparison = json.loads((REPO / "artifacts" / "2026-10-01-baseline-comparison"
                             / "comparison.json").read_text(encoding="utf-8"))
    panel = build_dashboard.render_baseline_panel(
        str(REPO / "artifacts" / "2026-10-01-baseline-comparison" / "comparison.json"))
    assert panel and panel in page
    for tool, label in build_dashboard.BASELINE_TOOLS:
        d = comparison["summary"][tool]["defect"]
        assert f'{label}</td><td class="num">{d["flagged"]} / {d["of"]}<' in panel
    assert build_dashboard.render_baseline_panel(str(tmp_path / "absent.json")) == ""


def test_dashboard_states_the_fail_closed_verdict_rules(page):
    # ScrolIQ adopted the recommended mapping in scrollq#55: missing
    # evidence (UNKNOWN) must read as DO NOT TRAIN, never fall through.
    assert "<b>UNKNOWN</b>" in page
    assert "https://github.com/Svyable/scrollq/pull/55" in page
    assert "2026-10-01-health-verdicts-fail-closed" in page


def test_dashboard_links_the_october_plan(page):
    assert 'href="./october-2026.html"' in page
    plan = (REPO / "docs" / "october-2026.html").read_text(encoding="utf-8")
    # A plan page: every goal names its exit evidence and starts as planned.
    assert plan.count('<span class="tag plan">planned</span>') == plan.count("<tr><td>G")
