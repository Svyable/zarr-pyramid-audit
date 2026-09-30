"""
httpstore.py -- portable read-only object access for remote research corpora.

Designed for cheap, polite, *evidence-grade* auditing of public data:
  - HEAD / byte-range GET so a survey can read headers instead of payloads
  - retry with exponential backoff + jitter on transient failures
  - a per-thread requests.Session (connection pooling; safe under a pool)
  - nginx/Apache autoindex directory listing
  - optional s3:// backend via s3fs (anonymous), same API

Deliberately read-only: there is no write path here, so an audit tool built
on it cannot mutate the corpus it is auditing.

No cloud login, no telemetry, no credentials required for public buckets.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter

__all__ = ["StoreError", "ObjectInfo", "HttpStore", "S3Store", "open_store"]

DEFAULT_UA = "vesuvius-audit/1.0 (public-data integrity survey; contact via GitHub issue)"

_HREF_RE = re.compile(r'href="([^"?][^"]*)"', re.IGNORECASE)


class StoreError(RuntimeError):
    """Raised when an object cannot be read after all retries."""


@dataclass
class ObjectInfo:
    path: str
    exists: bool
    size: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    status: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class _RetryPolicy:
    def __init__(self, tries: int = 5, base: float = 0.6, cap: float = 20.0):
        self.tries = max(1, int(tries))
        self.base = base
        self.cap = cap

    def sleep_for(self, attempt: int) -> float:
        # full jitter -- avoids synchronised retry storms from a worker pool
        return random.uniform(0.0, min(self.cap, self.base * (2 ** attempt)))


class HttpStore:
    """
    Read-only HTTP object store.

    Thread-safe: each thread gets its own Session, so a ThreadPoolExecutor
    can share one HttpStore instance without contention or shared-state bugs.
    """

    # status codes worth retrying; everything else is reported as-is
    RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        base_url: str = "",
        *,
        timeout: float = 120.0,
        tries: int = 5,
        user_agent: str = DEFAULT_UA,
        pool_maxsize: int = 64,
        max_rps: float | None = None,
    ):
        self.base_url = base_url.rstrip("/") + "/" if base_url else ""
        self.timeout = timeout
        self.retry = _RetryPolicy(tries=tries)
        self.user_agent = user_agent
        self.pool_maxsize = pool_maxsize
        self._local = threading.local()
        self._rate_lock = threading.Lock()
        self._min_interval = (1.0 / max_rps) if max_rps and max_rps > 0 else 0.0
        self._next_ok = 0.0

    # -- internals ----------------------------------------------------------
    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers["User-Agent"] = self.user_agent
            s.headers["Accept-Encoding"] = "identity"  # keep Content-Length honest
            ad = HTTPAdapter(pool_connections=self.pool_maxsize,
                             pool_maxsize=self.pool_maxsize,
                             max_retries=0)  # we do our own retries
            s.mount("http://", ad)
            s.mount("https://", ad)
            self._local.session = s
        return s

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        with self._rate_lock:
            now = time.monotonic()
            if now < self._next_ok:
                time.sleep(self._next_ok - now)
                now = time.monotonic()
            self._next_ok = now + self._min_interval

    def url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return urljoin(self.base_url, path.lstrip("/"))

    def _request(self, method: str, path: str, **kw) -> requests.Response:
        u = self.url(path)
        last: Exception | None = None
        for attempt in range(self.retry.tries):
            self._throttle()
            try:
                r = self._session().request(method, u, timeout=self.timeout, **kw)
                if r.status_code in self.RETRY_STATUS and attempt < self.retry.tries - 1:
                    time.sleep(self.retry.sleep_for(attempt))
                    continue
                return r
            except requests.RequestException as e:
                last = e
                if attempt < self.retry.tries - 1:
                    time.sleep(self.retry.sleep_for(attempt))
                    continue
        raise StoreError(f"{method} {u} failed after {self.retry.tries} tries: {last}")

    # -- public API ---------------------------------------------------------
    def head(self, path: str) -> ObjectInfo:
        """Cheapest possible existence + size probe. Falls back to a 1-byte
        ranged GET for servers that do not answer HEAD properly."""
        try:
            r = self._request("HEAD", path, allow_redirects=True)
        except StoreError as e:
            return ObjectInfo(path=path, exists=False, error=str(e))
        if r.status_code == 405 or (r.status_code == 200 and "Content-Length" not in r.headers):
            return self._head_via_range(path)
        if r.status_code == 404:
            return ObjectInfo(path=path, exists=False, status=404)
        if not r.ok:
            return ObjectInfo(path=path, exists=False, status=r.status_code,
                              error=f"HTTP {r.status_code}")
        cl = r.headers.get("Content-Length")
        return ObjectInfo(
            path=path, exists=True, status=r.status_code,
            size=int(cl) if cl and cl.isdigit() else None,
            etag=r.headers.get("ETag"),
            last_modified=r.headers.get("Last-Modified"),
        )

    def _head_via_range(self, path: str) -> ObjectInfo:
        try:
            r = self._request("GET", path, headers={"Range": "bytes=0-0"},
                              allow_redirects=True, stream=True)
        except StoreError as e:
            return ObjectInfo(path=path, exists=False, error=str(e))
        finally:
            pass
        if r.status_code == 404:
            r.close()
            return ObjectInfo(path=path, exists=False, status=404)
        size = None
        cr = r.headers.get("Content-Range")
        if cr and "/" in cr:
            tail = cr.rsplit("/", 1)[-1]
            if tail.isdigit():
                size = int(tail)
        info = ObjectInfo(path=path, exists=r.ok, status=r.status_code, size=size,
                          etag=r.headers.get("ETag"),
                          last_modified=r.headers.get("Last-Modified"))
        r.close()
        return info

    def get(self, path: str) -> bytes:
        r = self._request("GET", path, allow_redirects=True)
        if r.status_code == 404:
            raise StoreError(f"404 Not Found: {self.url(path)}")
        if not r.ok:
            raise StoreError(f"HTTP {r.status_code}: {self.url(path)}")
        return r.content

    def get_range(self, path: str, start: int, length: int) -> bytes:
        """Read [start, start+length). Raises StoreError on failure.
        Note: a server that ignores Range returns 200 and the whole object;
        we detect that and slice, so the caller always gets what it asked for."""
        end = start + length - 1
        r = self._request("GET", path, headers={"Range": f"bytes={start}-{end}"},
                          allow_redirects=True)
        if r.status_code == 404:
            raise StoreError(f"404 Not Found: {self.url(path)}")
        if r.status_code == 206:
            return r.content
        if r.status_code == 200:
            return r.content[start:start + length]
        raise StoreError(f"HTTP {r.status_code} on ranged GET: {self.url(path)}")

    def get_json(self, path: str) -> Any:
        import json
        return json.loads(self.get(path).decode("utf-8"))

    def try_json(self, path: str) -> tuple[Any | None, str | None]:
        """(obj, None) on success, (None, reason) on failure. Never raises."""
        try:
            return self.get_json(path), None
        except StoreError as e:
            return None, str(e)
        except Exception as e:  # malformed JSON
            return None, f"{type(e).__name__}: {e}"

    def list_dir(self, path: str) -> tuple[list[str], list[str]]:
        """
        Parse an nginx/Apache autoindex page.
        Returns (subdirs, files) as names relative to *path*, percent-decoded.
        """
        p = path if path.endswith("/") else path + "/"
        try:
            body = self.get(p).decode("utf-8", errors="replace")
        except StoreError:
            return [], []
        dirs: list[str] = []
        files: list[str] = []
        for href in _HREF_RE.findall(body):
            if href.startswith(("http://", "https://", "/", "?", "#")):
                continue
            if href in ("../", "..", "./"):
                continue
            name = unquote(href)
            if name.endswith("/"):
                dirs.append(name[:-1])
            else:
                files.append(name)
        return dirs, files


class S3Store:
    """
    Anonymous s3:// backend exposing the same surface as HttpStore, for
    corpora published to S3 rather than an autoindex. Imported lazily so the
    toolkit works with no s3fs installed.

    The S3 API endpoint is configurable because the global
    s3.amazonaws.com endpoint is not reachable from every network. Pass
    ``endpoint_url`` explicitly, or set ``AWS_ENDPOINT_URL_S3``; the
    regional endpoint (e.g. https://s3.us-east-1.amazonaws.com) is the
    usual right choice for a bucket known to live in one region.
    """

    def __init__(self, base_url: str = "", *, anon: bool = True,
                 endpoint_url: str | None = None,
                 region_name: str | None = None, **_ignored):
        import os
        import s3fs  # lazy
        endpoint_url = endpoint_url or os.environ.get("AWS_ENDPOINT_URL_S3")
        region_name = region_name or os.environ.get("AWS_REGION",
                                                    os.environ.get("AWS_DEFAULT_REGION"))
        client_kwargs: dict[str, Any] = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if region_name:
            client_kwargs["region_name"] = region_name
        self.fs = s3fs.S3FileSystem(
            anon=anon, client_kwargs=client_kwargs or None)
        self.base_url = base_url.rstrip("/") + "/" if base_url else ""
        self.endpoint_url = endpoint_url
        self.region_name = region_name

    def _p(self, path: str) -> str:
        if path.startswith("s3://"):
            return path[5:]
        return (self.base_url + path.lstrip("/"))[5:] if self.base_url.startswith("s3://") \
            else self.base_url + path.lstrip("/")

    def head(self, path: str) -> ObjectInfo:
        p = self._p(path)
        try:
            st = self.fs.info(p)
            return ObjectInfo(path=path, exists=True, size=st.get("size"),
                              etag=st.get("ETag"), last_modified=str(st.get("LastModified")))
        except FileNotFoundError:
            return ObjectInfo(path=path, exists=False, status=404)
        except Exception as e:
            return ObjectInfo(path=path, exists=False, error=f"{type(e).__name__}: {e}")

    def get(self, path: str) -> bytes:
        try:
            with self.fs.open(self._p(path), "rb") as fh:
                return fh.read()
        except Exception as e:
            raise StoreError(f"{type(e).__name__}: {e}") from e

    def get_range(self, path: str, start: int, length: int) -> bytes:
        try:
            with self.fs.open(self._p(path), "rb") as fh:
                fh.seek(start)
                return fh.read(length)
        except Exception as e:
            raise StoreError(f"{type(e).__name__}: {e}") from e

    def get_json(self, path: str) -> Any:
        import json
        return json.loads(self.get(path).decode("utf-8"))

    def try_json(self, path: str) -> tuple[Any | None, str | None]:
        try:
            return self.get_json(path), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def list_dir(self, path: str) -> tuple[list[str], list[str]]:
        p = self._p(path).rstrip("/")
        dirs: list[str] = []
        files: list[str] = []
        try:
            for e in self.fs.ls(p, detail=True):
                name = e["name"].rstrip("/").rsplit("/", 1)[-1]
                (dirs if e.get("type") == "directory" else files).append(name)
        except Exception:
            return [], []
        return dirs, files


def open_store(base_url: str, **kw):
    """Pick a backend from the URL scheme. s3:// -> S3Store, else HttpStore."""
    if urlparse(base_url).scheme == "s3":
        return S3Store(base_url, **kw)
    return HttpStore(base_url, **kw)
