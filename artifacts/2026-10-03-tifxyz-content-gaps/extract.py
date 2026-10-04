#!/usr/bin/env python3
"""Rebuild the named 32 MiB TIFXYZ content-gap inventory."""
from __future__ import annotations

import csv
import re
from pathlib import Path

SOURCE = Path("artifacts/2026-10-01-s3-tifxyz/tifxyz.findings.csv")
OUT = Path("artifacts/2026-10-03-tifxyz-content-gaps/gaps.csv")
PATTERN = re.compile(r"^(?P<channel>[xyz]\.tif) is (?P<bytes>\d+) bytes, above --max-content-bytes$")

rows = []
with SOURCE.open(newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        if row["code"] != "TIFXYZ_CONTENT_UNDECODED":
            continue
        match = PATTERN.match(row["detail"])
        if match is None:
            raise SystemExit(f"unexpected content-gap detail: {row['detail']!r}")
        rows.append({
            "root": row["root"],
            "channel": match.group("channel"),
            "bytes": int(match.group("bytes")),
        })

rows.sort(key=lambda row: (row["root"], row["channel"]))
if len(rows) != 148:
    raise SystemExit(f"expected 148 cap gaps, found {len(rows)}")

with OUT.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["root", "channel", "bytes"])
    writer.writeheader()
    writer.writerows(rows)
