"""
runio.py -- output handling for the research toolkit.

Core guarantee: this module NEVER silently overwrites an existing file.
Any path that already exists is renamed to "<name>.<YYYYmmdd-HHMMSS>.bak"
before the new file is created. If that backup name is itself taken
(two runs inside the same second), a numeric suffix is appended until a
free name is found -- so a backup can never clobber a backup either.

Portable: pure stdlib, no OS assumptions, no cloud dependency.
"""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

__all__ = [
    "timestamp",
    "backup_if_exists",
    "safe_open",
    "JsonlWriter",
    "CsvWriter",
    "RunManifest",
    "write_json",
]


def timestamp(when: float | None = None) -> str:
    """Local-time stamp used for backup suffixes: 20260908-031500."""
    t = time.localtime(when if when is not None else time.time())
    return time.strftime("%Y%m%d-%H%M%S", t)


def backup_if_exists(path: str | os.PathLike) -> Path | None:
    """
    If *path* exists, rename it to <path>.<timestamp>.bak and return the
    backup path. Otherwise return None. Never overwrites an existing backup.
    """
    p = Path(path)
    if not p.exists():
        return None
    base = f"{p.name}.{timestamp()}.bak"
    cand = p.with_name(base)
    n = 1
    while cand.exists():
        cand = p.with_name(f"{base}.{n}")
        n += 1
    p.rename(cand)
    return cand


def safe_open(path: str | os.PathLike, mode: str = "w", **kw):
    """
    open() that backs up any existing file first. Only for writing modes;
    append mode ('a') is deliberately rejected because appending to a file
    from a previous run silently mixes two runs' output together.
    """
    if "a" in mode:
        raise ValueError(
            "safe_open() refuses append mode: appending would mix runs. "
            "Write a new file instead -- the old one is backed up for you."
        )
    if "r" in mode and "+" not in mode:
        raise ValueError("safe_open() is for writing; use open() to read.")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    backup_if_exists(p)
    kw.setdefault("encoding", "utf-8")
    if "b" in mode:
        kw.pop("encoding", None)
    else:
        kw.setdefault("newline", "")
    return open(p, mode, **kw)


def write_json(path: str | os.PathLike, obj: Any, indent: int = 2) -> Path:
    """Write JSON, backing up any existing file. Returns the path written."""
    p = Path(path)
    with safe_open(p, "w") as fh:
        json.dump(obj, fh, indent=indent, sort_keys=False, default=str)
        fh.write("\n")
    return p


class JsonlWriter:
    """
    Streaming JSON-Lines writer. Backs up an existing file on open.
    Flushes every record so a long crawl that is interrupted still leaves
    a readable partial result on disk.
    """

    def __init__(self, path: str | os.PathLike, flush_every: int = 1):
        self.path = Path(path)
        self._fh = safe_open(self.path, "w")
        self._n = 0
        self._flush_every = max(1, int(flush_every))

    def write(self, rec: Mapping[str, Any]) -> None:
        self._fh.write(json.dumps(rec, default=str) + "\n")
        self._n += 1
        if self._n % self._flush_every == 0:
            self._fh.flush()

    @property
    def count(self) -> int:
        return self._n

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.flush()
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class CsvWriter:
    """
    CSV writer with a fixed header. Backs up an existing file on open.
    Rows may be dicts (missing keys become '') or sequences.
    """

    def __init__(self, path: str | os.PathLike, header: Sequence[str]):
        self.path = Path(path)
        self.header = list(header)
        self._fh = safe_open(self.path, "w")
        self._w = csv.writer(self._fh)
        self._w.writerow(self.header)
        self._n = 0

    def write(self, row: Mapping[str, Any] | Sequence[Any]) -> None:
        if isinstance(row, Mapping):
            out = [row.get(k, "") for k in self.header]
        else:
            out = list(row)
        self._w.writerow(out)
        self._n += 1
        if self._n % 50 == 0:
            self._fh.flush()

    @property
    def count(self) -> int:
        return self._n

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.flush()
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class RunManifest:
    """
    Records provenance for one run so a published finding can be reproduced:
    argv, host, python, package versions, UTC start/end, wall time, counters,
    and every output file written. Saved as JSON via write_json (so it too is
    backed up rather than overwritten).
    """

    def __init__(self, name: str, out_dir: str | os.PathLike, argv: Sequence[str] | None = None):
        self.name = name
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._t0 = time.time()
        self.data: dict[str, Any] = {
            "run_name": name,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "argv": list(argv if argv is not None else sys.argv),
            "cwd": os.getcwd(),
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "python_exe": sys.executable,
            "packages": self._pkg_versions(),
            "counters": {},
            "outputs": [],
            "notes": [],
        }

    @staticmethod
    def _pkg_versions() -> dict[str, str]:
        out: dict[str, str] = {}
        for mod in ("numpy", "zarr", "s3fs", "fsspec", "tifffile", "requests", "botocore"):
            try:
                m = __import__(mod)
                out[mod] = getattr(m, "__version__", "?")
            except Exception:
                out[mod] = "<not installed>"
        return out

    def count(self, key: str, n: int = 1) -> None:
        self.data["counters"][key] = self.data["counters"].get(key, 0) + n

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def note(self, msg: str) -> None:
        self.data["notes"].append(msg)

    def add_output(self, path: str | os.PathLike, desc: str = "") -> None:
        p = Path(path)
        self.data["outputs"].append({
            "path": str(p),
            "exists": p.exists(),
            "bytes": p.stat().st_size if p.exists() else None,
            "desc": desc,
        })

    def save(self, filename: str | None = None) -> Path:
        self.data["ended_utc"] = datetime.now(timezone.utc).isoformat()
        self.data["wall_seconds"] = round(time.time() - self._t0, 3)
        fn = filename or f"{self.name}.manifest.json"
        return write_json(self.out_dir / fn, self.data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.data["error"] = f"{exc_type.__name__}: {exc}"
        self.save()
        return False
