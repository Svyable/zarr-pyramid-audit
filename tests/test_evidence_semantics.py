"""Evidence semantics: failures must never masquerade as missing data."""
import io
import json

from zpa.audit_pyramid import audit_one
from zpa.httpstore import HttpStore, S3Store, StoreError
from zpa.zarrmeta import read_pyramid


GROUP = {"zarr_format": 2}
ATTRS = {"multiscales": [{"datasets": [{"path": "0"}]}]}
ARRAY = {
    "zarr_format": 2,
    "shape": [4, 4],
    "chunks": [2, 2],
    "dtype": "<u2",
    "fill_value": 0,
    "compressor": None,
    "order": "C",
    "dimension_separator": ".",
}
V3_ARRAY = {
    "zarr_format": 3,
    "node_type": "array",
    "shape": [8, 16],
    "data_type": "uint8",
    "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [4, 4]}},
    "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
    "fill_value": 0,
    "codecs": [{"name": "bytes"}],
    "attributes": {},
}


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


class Response:
    def __init__(self, status, body=b""):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Length": str(len(body))}

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def close(self):
        pass


def routed_store(routes):
    store = HttpStore("https://fixture.invalid/", tries=1)
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        outcome = routes.get(path, (404, b""))
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        return Response(status, body)

    store._request = request
    return store, calls


def audit_routes(routes, *, check_chunks=True):
    store, calls = routed_store(routes)
    pm = read_pyramid(store, "root", probe_extra_levels=0,
                      check_chunks=check_chunks)
    findings, levels, record = audit_one(pm)
    return pm, findings, levels, record, calls


def codes(findings):
    return [f["code"] for f in findings]


def test_successful_json_read_is_present():
    store, _ = routed_store({"root/.zgroup": (200, encoded(GROUP))})
    result = store.json_evidence("root/.zgroup")
    assert (result.state, result.reason) == ("PRESENT", None)


def test_confirmed_404_is_absent():
    store, _ = routed_store({"root/.zgroup": (404, b"")})
    result = store.json_evidence("root/.zgroup")
    assert (result.state, result.reason) == ("ABSENT", "NOT_FOUND")


def test_http_403_is_unknown_not_absent():
    store, _ = routed_store({"root/.zgroup": (403, b"")})
    result = store.json_evidence("root/.zgroup")
    assert (result.state, result.reason) == ("UNKNOWN", "FORBIDDEN")


def test_http_503_is_unknown_not_empty():
    _, findings, _, record, _ = audit_routes({
        "root/.zgroup": (503, b""),
        "root/zarr.json": (503, b""),
        "root/.zarray": (503, b""),
        "root/": (503, b""),
    })
    assert codes(findings) == ["ACCESS_UNKNOWN"]
    assert (record["evidence_state"], record["evidence_reason"]) == (
        "UNKNOWN", "SERVER_ERROR")


def test_transport_exceptions_are_unknown():
    cases = [
        (StoreError("GET failed: timeout"), "TIMEOUT"),
        (StoreError("GET failed: connection refused"), "CONNECTION_ERROR"),
    ]
    for error, reason in cases:
        store, _ = routed_store({"root/.zgroup": error})
        result = store.json_evidence("root/.zgroup")
        assert (result.state, result.reason) == ("UNKNOWN", reason)


def test_empty_listing_is_distinct_from_listing_failure():
    empty, _ = routed_store({"root/": (200, b"<html></html>")})
    failed, _ = routed_store({"root/": (503, b"")})
    empty_result = empty.list_dir_evidence("root")
    failed_result = failed.list_dir_evidence("root")
    assert (empty_result.state, empty_result.dirs, empty_result.files) == (
        "PRESENT", [], [])
    assert (failed_result.state, failed_result.reason) == ("UNKNOWN", "SERVER_ERROR")


def test_unknown_header_is_not_overridden_by_empty_listing():
    _, findings, _, record, _ = audit_routes({
        "root/.zgroup": (503, b""),
        "root/zarr.json": (404, b""),
        "root/.zarray": (404, b""),
        "root/": (200, b"<html></html>"),
    })
    assert codes(findings) == ["ACCESS_UNKNOWN"]
    assert record["evidence_state"] == "UNKNOWN"


def test_confirmed_missing_level_remains_level_missing():
    pm, findings, levels, _, _ = audit_routes({
        "root/.zgroup": (200, encoded(GROUP)),
        "root/.zattrs": (200, encoded(ATTRS)),
        "root/0/.zarray": (404, b""),
        "root/0/zarr.json": (404, b""),
    }, check_chunks=False)
    assert codes(findings) == ["LEVEL_MISSING"]
    assert pm.levels[0].evidence_state == "ABSENT"
    assert levels == []


def test_confirmed_empty_structure_remains_empty_zarr_dir():
    _, findings, _, record, _ = audit_routes({
        "root/.zgroup": (404, b""),
        "root/zarr.json": (404, b""),
        "root/.zarray": (404, b""),
        "root/": (200, b"<html></html>"),
    })
    assert codes(findings) == ["EMPTY_ZARR_DIR"]
    assert (record["evidence_state"], record["evidence_reason"]) == (
        "ABSENT", "EMPTY_STRUCTURE")


def test_confirmed_root_404_is_absent_not_empty():
    _, findings, _, record, _ = audit_routes({
        "root/.zgroup": (404, b""),
        "root/zarr.json": (404, b""),
        "root/.zarray": (404, b""),
        "root/": (404, b""),
    })
    assert codes(findings) == ["ROOT_ABSENT"]
    assert (record["evidence_state"], record["kind"]) == ("ABSENT", "absent")


def test_unsupported_listing_keeps_chunk_inventory_unknown():
    pm, findings, levels, _, _ = audit_routes({
        "root/.zgroup": (200, encoded(GROUP)),
        "root/.zattrs": (200, encoded(ATTRS)),
        "root/0/.zarray": (200, encoded(ARRAY)),
        "root/0/": (405, b""),
    })
    assert "LEVEL_NO_CHUNKS" not in codes(findings)
    assert (pm.levels[0].chunk_evidence_state,
            pm.levels[0].chunk_evidence_reason) == (
                "UNKNOWN", "LISTING_UNSUPPORTED")
    assert levels[0]["chunk_evidence_state"] == "UNKNOWN"


def test_malformed_metadata_is_unreadable_not_missing():
    _, findings, _, record, _ = audit_routes({
        "root/.zgroup": (200, b"{not-json"),
        "root/zarr.json": (404, b""),
        "root/.zarray": (404, b""),
    })
    assert codes(findings) == ["METADATA_UNREADABLE"]
    assert record["evidence_reason"] == "METADATA_UNREADABLE"


def test_header_audit_does_not_fetch_chunks():
    _, findings, _, _, calls = audit_routes({
        "root/.zgroup": (200, encoded(GROUP)),
        "root/.zattrs": (200, encoded(ATTRS)),
        "root/0/.zarray": (200, encoded(ARRAY)),
        "root/0/": (200, b'<a href=".zarray">h</a><a href="0.0">c</a>'),
    })
    assert findings == []
    requested = [path for _, path, _ in calls]
    assert requested == ["root/.zgroup", "root/.zattrs",
                         "root/0/.zarray", "root/0/"]


def test_confirmed_zero_chunk_inventory_remains_visible():
    _, findings, levels, _, _ = audit_routes({
        "root/.zgroup": (200, encoded(GROUP)),
        "root/.zattrs": (200, encoded(ATTRS)),
        "root/0/.zarray": (200, encoded(ARRAY)),
        "root/0/": (200, b'<a href=".zarray">header</a>'),
    })
    assert codes(findings) == ["LEVEL_NO_CHUNKS"]
    assert (levels[0]["has_chunks"],
            levels[0]["chunk_evidence_state"],
            levels[0]["chunk_evidence_reason"]) == (
                False, "ABSENT", "NO_CHUNK_KEYS")


def test_bare_v3_array_is_classified_as_array_not_broken_group():
    _, findings, _, record, _ = audit_routes({
        "root/.zgroup": (404, b""),
        "root/zarr.json": (200, encoded(V3_ARRAY)),
    }, check_chunks=False)
    assert codes(findings) == ["BARE_ARRAY"]
    assert record["kind"] == "array"


def test_s3_store_preserves_object_evidence():
    class FakeFS:
        def __init__(self, outcome):
            self.outcome = outcome

        def open(self, *_args, **_kwargs):
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return io.BytesIO(self.outcome)

    cases = [
        (encoded(GROUP), "PRESENT", None),
        (FileNotFoundError("missing"), "ABSENT", "NOT_FOUND"),
        (PermissionError("access denied"), "UNKNOWN", "FORBIDDEN"),
        (OSError("HTTP 503 service unavailable"), "UNKNOWN", "SERVER_ERROR"),
        (TimeoutError("timed out"), "UNKNOWN", "TIMEOUT"),
    ]
    for outcome, state, reason in cases:
        store = S3Store.__new__(S3Store)
        store.fs = FakeFS(outcome)
        store.base_url = "s3://fixture/"
        result = store.json_evidence("root/.zgroup")
        assert (result.state, result.reason) == (state, reason)
