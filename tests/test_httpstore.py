from io import BytesIO
from types import SimpleNamespace

import pytest

from zpa.httpstore import HttpStore, S3Store, StoreError


class _RetryResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def close(self):
        self.closed = True


def test_http_retry_honors_retry_after_and_closes_response(monkeypatch):
    store = HttpStore("https://example.test", tries=2)
    rate_limited = _RetryResponse(429, {"Retry-After": "3"})
    responses = [
        rate_limited,
        _RetryResponse(200),
    ]
    monkeypatch.setattr(
        store, "_session",
        lambda: SimpleNamespace(request=lambda *args, **kwargs: responses.pop(0)),
    )
    monkeypatch.setattr(store.retry, "sleep_for", lambda attempt: 0.25)
    sleeps = []
    monkeypatch.setattr("zpa.httpstore.time.sleep", sleeps.append)

    response = store._request("GET", "object")

    assert response.status_code == 200
    assert sleeps == [3.0]
    assert rate_limited.closed is True
    assert responses == []


def test_http_retry_after_date_is_bounded_by_retry_cap(monkeypatch):
    store = HttpStore("https://example.test")
    monkeypatch.setattr(store.retry, "sleep_for", lambda attempt: 0.25)
    monkeypatch.setattr("zpa.httpstore.time.time", lambda: 0.0)

    delay = store.retry.delay_for(0, "Thu, 01 Jan 1970 00:01:00 GMT")

    assert delay == store.retry.cap


def test_http_retry_ignores_malformed_retry_after(monkeypatch):
    store = HttpStore("https://example.test")
    monkeypatch.setattr(store.retry, "sleep_for", lambda attempt: 0.75)

    assert store.retry.delay_for(0, "not-a-delay") == 0.75


def test_http_get_range_rejects_short_partial_response(monkeypatch):
    store = HttpStore("https://example.test")
    response = SimpleNamespace(status_code=206, content=b"ab")
    monkeypatch.setattr(store, "_request", lambda *args, **kwargs: response)

    with pytest.raises(StoreError, match="expected 4 bytes, got 2"):
        store.get_range("object", 0, 4)


def test_http_get_range_slices_full_response_exactly(monkeypatch):
    store = HttpStore("https://example.test")
    response = SimpleNamespace(status_code=200, content=b"012345")
    monkeypatch.setattr(store, "_request", lambda *args, **kwargs: response)

    assert store.get_range("object", 2, 3) == b"234"


def test_http_get_range_rejects_short_full_response(monkeypatch):
    store = HttpStore("https://example.test")
    response = SimpleNamespace(status_code=200, content=b"abc")
    monkeypatch.setattr(store, "_request", lambda *args, **kwargs: response)

    with pytest.raises(StoreError, match="expected 4 bytes, got 2"):
        store.get_range("object", 1, 4)


def test_s3_get_range_rejects_short_read():
    class FakeFS:
        def open(self, path, mode):
            return BytesIO(b"abc")

    store = object.__new__(S3Store)
    store.base_url = "s3://bucket/"
    store.fs = FakeFS()

    with pytest.raises(StoreError, match="expected 4 bytes, got 2"):
        store.get_range("object", 1, 4)


def test_zero_length_range_is_empty_without_io(monkeypatch):
    store = HttpStore("https://example.test")
    monkeypatch.setattr(
        store,
        "_request",
        lambda *args, **kwargs: pytest.fail("zero-length range should not perform IO"),
    )

    assert store.get_range("object", 5, 0) == b""


def test_http_get_range_accepts_matching_content_range(monkeypatch):
    store = HttpStore("https://example.test")
    response = SimpleNamespace(
        status_code=206,
        content=b"234",
        headers={"Content-Range": "bytes 2-4/10"},
    )
    monkeypatch.setattr(store, "_request", lambda *args, **kwargs: response)

    assert store.get_range("object", 2, 3) == b"234"


@pytest.mark.parametrize(
    "content_range",
    [
        "",
        "bytes 1-3/10",
        "bytes 2-5/10",
        "items 2-4/10",
    ],
)
def test_http_get_range_rejects_wrong_content_range(monkeypatch, content_range):
    store = HttpStore("https://example.test")
    response = SimpleNamespace(
        status_code=206,
        content=b"234",
        headers={"Content-Range": content_range},
    )
    monkeypatch.setattr(store, "_request", lambda *args, **kwargs: response)

    with pytest.raises(StoreError, match="invalid Content-Range"):
        store.get_range("object", 2, 3)


@pytest.mark.parametrize("header", ["bytes 2-4/6", "bytes 2-4/*", "BYTES 2-4/5"])
def test_http_range_accepts_exact_content_range(monkeypatch, header):
    store = HttpStore("https://example.test")
    def request(method, path, **kwargs):
        assert kwargs["headers"]["Range"] == "bytes=2-4"
        return SimpleNamespace(status_code=206, content=b"234",
                               headers={"Content-Range": header})
    monkeypatch.setattr(store, "_request", request)
    assert store.get_range("object", 2, 3) == b"234"


@pytest.mark.parametrize("header", [
    "", "bytes 0-2/6", "bytes 2-5/6", "bytes 2-4/4", "bytes 2-4/0",
    "bytes */6", "items 2-4/6", "bytes 2-4/6 junk", "bytes 2-4/6\n",
])
def test_http_range_rejects_invalid_content_range(monkeypatch, header):
    store = HttpStore("https://example.test")
    response = SimpleNamespace(status_code=206, content=b"234",
                               headers={"Content-Range": header})
    monkeypatch.setattr(store, "_request", lambda *a, **kw: response)
    with pytest.raises(StoreError, match="invalid Content-Range"):
        store.get_range("object", 2, 3)
