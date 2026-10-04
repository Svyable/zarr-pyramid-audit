"""Golden outputs for the fixture corpus (fixtures/).

Each fixture isolates one property; its expected/<case>.json pins the
structured result -- codes, severities, evidence states, coverage, gate
verdict, consumer verdict, chunk-probe statuses. A behaviour change shows
up here as a reviewable diff. Regenerate deliberately with
``python fixtures/corpus.py expected``.
"""
from __future__ import annotations

import filecmp
import functools
import http.server
import json
import os
import re
import sys
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "fixtures"))

import corpus  # noqa: E402

from zpa.audit_pyramid import SEVERITY  # noqa: E402
from zpa.chunkscan import SCAN_SEVERITY  # noqa: E402
from zpa.httpstore import HttpStore, StoreError  # noqa: E402
from zpa.report import validate_report  # noqa: E402

ZARR_NAMES = [n for n, *_ in corpus.ZARR_CASES]
TIFXYZ_NAMES = [n for n, *_ in corpus.TIFXYZ_CASES]
ALL_NAMES = corpus.all_case_names()


def expected(name: str) -> dict:
    with open(os.path.join(corpus.EXPECTED_DIR, f"{name}.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def test_every_case_has_exactly_one_golden_file():
    on_disk = {f[:-5] for f in os.listdir(corpus.EXPECTED_DIR)
               if f.endswith(".json")}
    assert on_disk == set(ALL_NAMES)
    assert len(ALL_NAMES) == len(set(ALL_NAMES))


def _walk_equal(built_root, committed_root):
    def walk(root):
        out = {}
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                full = os.path.join(dirpath, f)
                out[os.path.relpath(full, root)] = full
        return out

    built, committed = walk(built_root), walk(committed_root)
    assert sorted(built) == sorted(committed)
    for rel, path in built.items():
        if filecmp.cmp(path, committed[rel], shallow=False):
            continue
        # Blosc framing can differ across c-blosc builds; the payload cannot.
        from numcodecs import Blosc
        with open(path, "rb") as a, open(committed[rel], "rb") as b:
            assert Blosc().decode(a.read()) == Blosc().decode(b.read()), rel


def test_committed_zarr_trees_match_the_builder(tmp_path):
    corpus.build(str(tmp_path))
    _walk_equal(tmp_path, corpus.ZARR_DIR)


def test_committed_surfaces_match_the_builder(tmp_path):
    corpus.build_surfaces(str(tmp_path))
    _walk_equal(tmp_path, corpus.SURF_DIR)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_case_matches_golden(name):
    assert corpus.compute(name) == expected(name)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_case_report_validates_against_schema(name):
    if name in corpus.HTTP_CASES:
        _, report = corpus.run_http_case(name)
    elif name in TIFXYZ_NAMES:
        _, report = corpus.run_tifxyz_case(name)
    else:
        _, report = corpus.run_zarr_case(name)
    assert validate_report(report) == []
    try:
        import jsonschema
    except ImportError:
        return
    from zpa.report import load_schema, schema_kind
    jsonschema.validate(report, load_schema(schema_kind(report)))


# ---- transport invariance: the same trees over real HTTP -------------------

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def corpus_server():
    handler = functools.partial(_QuietHandler, directory=corpus.HERE)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("name", ZARR_NAMES)
def test_zarr_case_is_transport_invariant_over_http(name, corpus_server,
                                                    monkeypatch):
    """Python's http.server is an autoindex that ignores Range headers --
    the same tree must yield the same golden result through HttpStore."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    store = HttpStore(corpus_server + "zarr/", tries=1, timeout=10)
    projection, _ = corpus.run_zarr_case(name, store=store)
    assert corpus.golden(name, projection) == expected(name)


@pytest.mark.parametrize("name", TIFXYZ_NAMES)
def test_tifxyz_case_is_transport_invariant_over_http(name, corpus_server,
                                                      monkeypatch):
    """Same surfaces over HTTP: HEAD sizes, TIFF headers read by strict
    range requests (answered with 200 + full body here), same golden."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    store = HttpStore(corpus_server + "surfaces/", tries=1, timeout=10)
    projection, _ = corpus.run_tifxyz_case(name, store=store)
    assert corpus.golden(name, projection) == expected(name)


# ---- byte-range edge cases --------------------------------------------------

RANGE_CASES = corpus.load_range_cases()


@pytest.mark.parametrize("case", RANGE_CASES, ids=[c["name"] for c in RANGE_CASES])
def test_range_case(case):
    resp = case["response"]
    store = HttpStore("https://fixture.invalid/", tries=1)
    sent = []

    def request(method, path, **kw):
        sent.append(kw.get("headers", {}).get("Range"))
        return corpus.ReplayResponse(resp["status"], resp["text"].encode(),
                                     resp.get("headers"))

    store._request = request
    call = case["call"]
    if call["method"] == "get_range":
        run = lambda: store.get_range("obj", call["start"], call["length"])  # noqa: E731
        want_header = f"bytes={call['start']}-{call['start'] + call['length'] - 1}"
    else:
        run = lambda: store.get_suffix("obj", call["length"])  # noqa: E731
        want_header = f"bytes=-{call['length']}"
    exp = case["expect"]
    if "bytes" in exp:
        assert run() == exp["bytes"].encode()
    else:
        assert exp["error"] == "StoreError"
        with pytest.raises(StoreError) as info:
            run()
        assert re.search(exp["match"], str(info.value)), str(info.value)
    assert sent == [want_header]


# ---- the corpus must exercise the whole contract ---------------------------

# Codes no fixture can produce, and where they are covered instead.
COVERAGE_EXEMPT = {
    "CHUNK_SAMPLE_MISSING": "volcomp shard-index path only (tests/test_volcomp.py)",
    "CHUNK_SAMPLE_ABSENT": "probe_level skips absent keys; see sparse_level",
    "CHUNK_FETCH_ERROR": "transport failure; range-cases.json pins the reads",
    "SHARD_INDEX_CHECKSUM_MISMATCH":
        "volcomp shard-index path only (tests/test_chunkscan_index_checksum.py)",
    "TIFXYZ_CONTENT_UNDECODED":
        "needs a layout no decoder handles (tests/test_tifxyz.py)",
}

_STATUS_CODE = {"populated": "CHUNK_SAMPLE_POPULATED",
                "empty": "CHUNK_SAMPLE_EMPTY",
                "undecodable": "CHUNK_UNDECODEABLE"}


def test_every_check_code_is_exercised_by_a_fixture():
    seen = set()
    for name in ALL_NAMES:
        g = expected(name)
        seen.update(f["code"] for f in g["findings"])
        seen.update(g.get("gate", {}).get("codes", []))
        for lvl in g.get("chunk_scan", []):
            seen.update(lvl["level_codes"])
            seen.update(_STATUS_CODE[s] for s in lvl["samples"])
    # The exact-target-bounds control reuses the committed clean TIFXYZ bytes
    # under a deliberately smaller CT grid, so its golden lives outside
    # expected/ rather than duplicating binary fixture files.
    with open(
        os.path.join(corpus.HERE, "tifxyz-target-bounds.expected.json"),
        encoding="utf-8",
    ) as fh:
        seen.add(json.load(fh)["finding"]["code"])

    from zpa.tifxyz import TIFXYZ_SEVERITY
    wanted = (set(SEVERITY) | set(SCAN_SEVERITY) | set(TIFXYZ_SEVERITY)
              | {"GATE_UNREADABLE"})
    missing = wanted - seen - set(COVERAGE_EXEMPT)
    assert not missing, f"add a fixture for: {sorted(missing)}"


def test_every_integrity_state_and_verdict_is_exercised():
    states = {expected(n)["integrity"] for n in ALL_NAMES}
    verdicts = {expected(n)["consumer_verdict"] for n in ALL_NAMES}
    assert states == {"PASS", "WARN", "UNKNOWN", "FAIL"}
    assert verdicts == {"DEFER_TO_QUALITY", "CAUTION", "DO NOT TRAIN"}


def test_unknown_evidence_is_never_a_clean_result():
    for name in ALL_NAMES:
        g = expected(name)
        if any(f["evidence_state"] == "UNKNOWN" for f in g["findings"]):
            assert g["integrity"] in ("UNKNOWN", "FAIL"), name
            assert g["consumer_verdict"] != "DEFER_TO_QUALITY", name
            if "gate" in g:
                assert g["gate"]["fail"] is True, name


def test_missing_empty_and_zero_filled_stay_distinct():
    """Lesson 1: three different things, three different results."""
    def scan(name):
        return {lvl["level"]: lvl for lvl in expected(name)["chunk_scan"]}

    # absent keys (sparse) never make a level empty
    assert not any(l["all_empty"] for l in scan("sparse_level").values())
    # stored all-fill chunks are flagged for review, at medium severity
    assert scan("present_all_fill")["0"]["level_codes"] == ["CHUNK_SAMPLE_ALL_EMPTY"]
    assert SCAN_SEVERITY["CHUNK_SAMPLE_ALL_EMPTY"] == "medium"
    # zeros are data when the fill value is not zero
    assert set(scan("zero_data_nonzero_fill")["0"]["samples"]) == {"populated"}
    # a fill of 255 (or NaN) is empty even though no byte is zero
    assert scan("all_fill_nonzero")["0"]["all_empty"] is True
    assert scan("nan_fill_all_empty")["0"]["all_empty"] is True
    # a level the sampler cannot cover is a gap, not an empty level
    assert scan("sparse_unsampled")["0"]["level_codes"] == ["CHUNK_LEVEL_NO_SAMPLES"]


def test_fixture_readme_matches_the_goldens():
    with open(os.path.join(REPO, "fixtures", "README.md"), encoding="utf-8") as fh:
        text = fh.read()
    assert text.endswith("## Cases\n\n" + corpus.case_table()), (
        "fixtures/README.md is stale: run python fixtures/corpus.py readme")
    assert (f"{len(corpus.ZARR_CASES)} on-disk cases, "
            f"{len(corpus.HTTP_CASES)} replayed-HTTP cases") in text
    assert f"{len(corpus.TIFXYZ_CASES)} tifxyz surface cases" in text
    assert f"{len(RANGE_CASES)} byte-range cases" in " ".join(text.split())
