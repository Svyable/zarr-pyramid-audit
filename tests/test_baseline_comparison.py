from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_compare_baselines():
    path = Path(__file__).parents[1] / "fixtures" / "compare_baselines.py"
    spec = importlib.util.spec_from_file_location("compare_baselines_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zarr_lint_adapter_reports_clean(monkeypatch):
    module = _load_compare_baselines()
    fake = types.SimpleNamespace(lint=lambda path: {"diagnostics": []})
    monkeypatch.setitem(sys.modules, "zarr_lint", fake)

    assert module.zarr_lint_("fixture.zarr") == {
        "outcome": "clean",
        "detail": "0 diagnostic(s)",
        "rules": [],
    }


def test_zarr_lint_adapter_preserves_rule_ids(monkeypatch):
    module = _load_compare_baselines()
    fake = types.SimpleNamespace(
        lint=lambda path: {
            "diagnostics": [
                {"rule": "metadata/invalid-json"},
                {"rule": "array/rank-mismatch"},
                {"rule": "metadata/invalid-json"},
            ]
        }
    )
    monkeypatch.setitem(sys.modules, "zarr_lint", fake)

    assert module.zarr_lint_("fixture.zarr") == {
        "outcome": "findings",
        "detail": "3 diagnostic(s)",
        "rules": ["array/rank-mismatch", "metadata/invalid-json"],
    }


def test_zarr_lint_adapter_does_not_hide_tool_errors(monkeypatch):
    module = _load_compare_baselines()

    def explode(path):
        raise RuntimeError("tool failed")

    monkeypatch.setitem(sys.modules, "zarr_lint", types.SimpleNamespace(lint=explode))

    try:
        module.zarr_lint_("fixture.zarr")
    except RuntimeError as exc:
        assert str(exc) == "tool failed"
    else:
        raise AssertionError("zarr-lint infrastructure errors must fail the benchmark")
