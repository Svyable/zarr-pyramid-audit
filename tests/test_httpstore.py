from io import BytesIO
from types import SimpleNamespace

import pytest

from zpa.httpstore import HttpStore, S3Store, StoreError


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
