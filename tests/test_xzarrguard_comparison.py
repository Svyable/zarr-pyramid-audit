from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_compare_xzarrguard():
    path = Path(__file__).parents[1] / "fixtures" / "compare_xzarrguard.py"
    spec = importlib.util.spec_from_file_location("compare_xzarrguard_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3_fixture_detection(tmp_path):
    module = _load_compare_xzarrguard()
    store = tmp_path / "case.zarr"
    store.mkdir()
    assert not module.is_v3_fixture(str(store))
    (store / "zarr.json").write_text("{}", encoding="utf-8")
    assert module.is_v3_fixture(str(store))


def test_xzarrguard_adapter_sums_completeness_evidence(monkeypatch):
    module = _load_compare_xzarrguard()

    class Report:
        def to_dict(self):
            return {
                "ok": False,
                "errors": [],
                "variables": {
                    "a": {
                        "expected_chunks": 4,
                        "missing_unexpected": [{"coord": [0], "key": "c/0"}],
                        "missing_allowed": [{"coord": [1], "key": "c/1"}],
                        "stale_manifest": [],
                        "manifest_key_mismatch": [],
                        "manifest_out_of_bounds": [],
                    },
                    "b": {
                        "expected_chunks": 3,
                        "missing_unexpected": [],
                        "missing_allowed": [],
                        "stale_manifest": [{"coord": [0], "key": "c/0"}],
                        "manifest_key_mismatch": [{"coord": [1], "key": "bad"}],
                        "manifest_out_of_bounds": [],
                    },
                },
            }

    fake = types.SimpleNamespace(check_store=lambda path: Report())
    monkeypatch.setitem(sys.modules, "xzarrguard", fake)

    assert module.xzarrguard_("fixture.zarr") == {
        "outcome": "incomplete",
        "detail": "",
        "ok": False,
        "errors": [],
        "expected_chunks": 7,
        "missing_unexpected": 1,
        "missing_allowed": 1,
        "manifest_issues": 2,
    }


def test_xzarrguard_adapter_preserves_tool_errors(monkeypatch):
    module = _load_compare_xzarrguard()

    def explode(path):
        raise RuntimeError("tool failed")

    monkeypatch.setitem(sys.modules, "xzarrguard", types.SimpleNamespace(check_store=explode))

    assert module.xzarrguard_("fixture.zarr") == {
        "outcome": "error",
        "detail": "RuntimeError: tool failed",
        "ok": None,
        "errors": [],
        "expected_chunks": None,
        "missing_unexpected": None,
        "missing_allowed": None,
        "manifest_issues": None,
    }
