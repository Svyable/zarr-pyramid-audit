"""Integration surface: gate policy, local stores, examples, benchmark."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from zpa import gate
from zpa.bench import bench_root, markdown_table
from zpa.httpstore import LocalStore, StoreError, open_store
from zpa.report import SCHEMA_VERSION, validate_report

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO, "fixtures", "zarr")


def run_gate(tmp_path, *extra, roots=("clean_v2.zarr",)):
    out = tmp_path / "gate.json"
    argv = ["--base", CORPUS, "--workers", "1", "--out", str(out), *extra]
    for root in roots:
        argv += ["--root", root]
    code = gate.main(argv)
    return code, json.loads(out.read_text())


def test_open_store_picks_local_backend_for_paths():
    assert isinstance(open_store(CORPUS), LocalStore)
    assert isinstance(open_store("file://" + CORPUS), LocalStore)
    assert type(open_store("https://example.test/")).__name__ == "HttpStore"


def test_local_store_refuses_paths_outside_its_root():
    store = LocalStore(CORPUS)
    with pytest.raises(StoreError, match="escapes store root"):
        store.get("../../pyproject.toml")


def test_gate_report_is_versioned_and_schema_valid(tmp_path):
    code, report = run_gate(tmp_path, roots=("clean_v2.zarr", "fill_drift.zarr"))
    assert code == 0
    assert report["schema_version"] == SCHEMA_VERSION
    for result in report["results"]:
        assert validate_report(result["report"]) == []
    drift = next(r for r in report["results"] if r["root"] == "fill_drift.zarr")
    assert drift["integrity"] == "WARN"
    assert [f["code"] for f in drift["below_threshold"]] == ["FILL_DRIFT"]


def test_gate_fails_on_high_and_on_threshold(tmp_path):
    assert run_gate(tmp_path, roots=("level_no_chunks.zarr",))[0] == 1
    assert run_gate(tmp_path, "--fail-on", "medium", roots=("fill_drift.zarr",))[0] == 1


def test_gate_fails_closed_on_absent_root(tmp_path, capsys):
    code, report = run_gate(tmp_path, roots=("root_absent.zarr",))
    assert code == 1
    result = report["results"][0]
    assert result["verdict"] == "absent"
    assert result["findings"][0]["code"] == "GATE_ROOT_ABSENT"
    assert result["integrity"] == "UNKNOWN"
    assert "ABSENT" in capsys.readouterr().out

    code, report = run_gate(tmp_path, "--allow-absent", roots=("root_absent.zarr",))
    assert code == 0
    assert report["results"][0]["verdict"] == "absent"


def test_pass_lines_show_below_threshold_codes(tmp_path, capsys):
    run_gate(tmp_path, roots=("compressor_drift.zarr",))
    assert "PASS  compressor_drift.zarr [COMPRESSOR_DRIFT]" in capsys.readouterr().out


def test_python_api_example_runs_offline():
    sys.path.insert(0, os.path.join(REPO, "examples"))
    try:
        import python_api
    finally:
        sys.path.pop(0)
    decisions = python_api.triage(python_api.DEFAULT_BASE, python_api.DEFAULT_ROOTS)
    by_root = {d["root"]: d for d in decisions}
    assert by_root["clean_v2.zarr"]["verdict"] == "DEFER_TO_QUALITY"
    assert by_root["fill_drift.zarr"]["verdict"] == "CAUTION"
    assert by_root["level_no_chunks.zarr"]["verdict"] == "DO NOT TRAIN"
    assert by_root["root_absent.zarr"]["integrity"] == "UNKNOWN"
    assert by_root["root_absent.zarr"]["weight"] == 0.0


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("zpa-gate") is None,
                    reason="needs bash and an installed zpa-gate")
def test_preflight_script(tmp_path):
    script = os.path.join(REPO, "examples", "preflight.sh")
    env = {**os.environ, "ZPA_OUT": str(tmp_path / "pf.json")}
    ok = subprocess.run(["bash", script, CORPUS, "clean_v2.zarr"],
                        env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    bad = subprocess.run(["bash", script, CORPUS, "clean_v2.zarr", "missing_level.zarr"],
                         env=env, capture_output=True, text=True)
    assert bad.returncode == 1
    assert json.loads((tmp_path / "pf.json").read_text())["n_fail"] == 1


def test_workflow_example_only_uses_real_gate_flags():
    with open(os.path.join(REPO, "examples", "github-actions", "zarr-gate.yml"),
              encoding="utf-8") as fh:
        text = fh.read()
    flags = set(re.findall(r"(--[a-z][a-z-]+)", text))
    known = {a for action in gate.parse_args(["--base", "x", "--root", "y"]).__dict__
             for a in ["--" + action.replace("_", "-")]}
    assert flags <= known, flags - known


def test_bench_counts_header_and_probe_cost():
    rec = bench_root(CORPUS, "clean_v2.zarr", samples_per_level=3)
    header, probe = rec["header"], rec["probe"]
    assert rec["integrity"] == "PASS"
    # .zgroup, .zattrs, 3 level headers -> 5 metadata reads; 3 listings;
    # 2 HEADs for the undeclared-level probe (3/.zarray, 3/zarr.json)
    assert header["calls"] == {"metadata_reads": 5, "listings": 3,
                               "existence_probes": 2}
    assert header["payload_bytes"] > 0
    # 3 + 1 + 1 present chunks, each a single prefix read (nonzero data)
    assert probe["statuses"] == {"populated": 5}
    assert probe["calls"] == {"existence_probes": 5, "chunk_reads": 5}
    assert probe["payload_bytes"] == 3 * 256 + 256 + 32
    assert "clean_v2.zarr" in markdown_table([rec])
