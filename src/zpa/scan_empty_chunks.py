#!/usr/bin/env python3
"""
scan_empty_chunks.py -- sampled chunk-content probe for Zarr pyramids.

The header-only audit tells you chunk keys exist. This tells you whether
the chunks that exist hold data: it downloads K sampled chunks per level
(first/middle/last of the chunk grid), decodes them, and reports whether
each is populated, all fill_value, or undecodable.

Findings:
  CHUNK_SAMPLE_POPULATED   [info]   a sampled chunk holds non-fill data --
                                    the level is genuinely populated
  CHUNK_SAMPLE_ALL_EMPTY   [medium] every sampled chunk in the level decodes
                                    to fill_value -- suspicious, needs a human
                                    (genuinely empty background is possible)
  CHUNK_UNDECODEABLE       [low]    chunk fetched but codec not supported
  CHUNK_FETCH_ERROR        [low]    chunk key vanished / download failed
  CHUNK_SAMPLE_MISSING     [info]   inner chunk absent from a v3 shard index
                                    (masked background legitimately unstored)
  CHUNK_SAMPLE_ABSENT      [info]   v2 chunk key not present (sparse level)
  CHUNK_LEVEL_NO_CHUNKS    [info]   level holds no stored chunks at all
                                    (audit-flagged, probe-confirmed)
  CHUNK_LEVEL_NO_SAMPLES   [info]   sparse level the spread sampling could not
                                    cover -- a coverage gap, not a finding

Usage:
    python bin/scan_empty_chunks.py --base s3://vesuvius-challenge-open-data/ \
        --levels-jsonl artifacts/2026-09-29-s3/audit_pyramid.levels.jsonl \
        --root-filter 1.129um-0.22m-59keV-volume-20260521123630-L1 \
        --samples-per-level 3 --out-dir tmp/chunkscan
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter

from zpa.chunkscan import (probe_level, probe_level_v3_sharded,
                            probe_level_volcomp_sharded)  # noqa: E402
from zpa.httpstore import open_store                        # noqa: E402
from zpa.pool import parallel_map                           # noqa: E402
from zpa.runio import RunManifest, write_json               # noqa: E402

FINDING_HEADER = ["code", "severity", "root", "level", "chunk",
                  "detail", "bytes_fetched"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--levels-jsonl", required=True,
                    help="audit_pyramid.levels.jsonl from a header-only audit")
    ap.add_argument("--root-filter", action="append", default=[],
                    help="only roots containing this substring (repeatable)")
    ap.add_argument("--random-roots", type=int, default=0,
                    help="add N random roots (seeded) beyond the filter")
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--samples-per-level", type=int, default=3)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--limit-roots", type=int, default=None)
    ap.add_argument("--only-sharded", action="store_true",
                    help="only probe v3 sharded (sharding_indexed) levels")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp",
        "chunkscan")
    os.makedirs(out_dir, exist_ok=True)

    # Group level records by root; keep levels that claimed chunk presence.
    by_root: dict[str, list[dict]] = {}
    with open(args.levels_jsonl, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if not r.get("present"):
                continue
            if not r.get("shape") or not r.get("chunks"):
                continue
            if args.only_sharded and \
                    (r.get("compressor") or "").lower() != "sharding_indexed":
                continue
            by_root.setdefault(r["root"], []).append(r)

    roots = [r for r in by_root
             if not args.root_filter
             or any(f in r for f in args.root_filter)]
    if args.random_roots:
        rng = random.Random(args.seed)
        pool = [r for r in by_root if r not in roots]
        roots += rng.sample(pool, min(args.random_roots, len(pool)))
    if args.limit_roots:
        roots = roots[: args.limit_roots]
    if not roots:
        print("no roots selected", file=sys.stderr)
        return 2

    store = open_store(args.base)

    fd_path = os.path.join(out_dir, "scan_empty_chunks.findings.csv")
    sm_path = os.path.join(out_dir, "scan_empty_chunks.summary.json")
    codes = Counter()
    bytes_total = 0
    levels_scanned = 0
    levels_all_empty = []

    with RunManifest("scan_empty_chunks", out_dir) as man, \
         open(fd_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FINDING_HEADER)
        w.writeheader()
        man.set("base", args.base)
        man.set("n_roots", len(roots))
        man.set("samples_per_level", args.samples_per_level)

        import os as _os
        s3_endpoint = _os.environ.get("AWS_ENDPOINT_URL_S3")
        bucket = args.base[5:].rstrip("/") if args.base.startswith("s3://") \
            else ""

        def probe_rec(root: str, rec: dict):
            # v3 sharded levels: try the volcomp byte-range probe first
            # (self-detects the codec from zarr.json; works on any base).
            # Falls back to zarr-python window reads on s3://, which need
            # the S3 store rather than plain HTTPS.
            if (rec.get("compressor") or "").lower() == "sharding_indexed":
                samples = probe_level_volcomp_sharded(
                    store, root, rec,
                    samples_per_level=args.samples_per_level)
                if not (len(samples) == 1
                        and samples[0].status == "undecodable"
                        and "not volcomp" in samples[0].detail):
                    return samples
                if bucket:
                    return probe_level_v3_sharded(
                        bucket, root, rec,
                        samples_per_level=args.samples_per_level,
                        endpoint_url=s3_endpoint)
                return samples
            return probe_level(store, root, rec,
                               samples_per_level=args.samples_per_level)

        def work(root: str):
            return root, [(str(rec.get("level")),
                           rec.get("has_chunks"),
                           probe_rec(root, rec))
                          for rec in sorted(by_root[root],
                                            key=lambda r: r.get("index", 0))]

        def emit(code, severity, root, level, chunk, detail, bf):
            w.writerow({"code": code, "severity": severity, "root": root,
                        "level": level, "chunk": chunk, "detail": detail,
                        "bytes_fetched": bf})
            codes[code] += 1

        for res in parallel_map(work, roots, workers=args.workers,
                                label="probing chunks"):
            if not res.ok:
                man.count("probe_errors")
                emit("CHUNK_FETCH_ERROR", "low", res.item, "", "",
                     res.error, 0)
                continue
            root, per_level = res.value
            for level, has_chunks, samples in per_level:
                levels_scanned += 1
                if not samples:
                    if has_chunks is False:
                        # Audit-flagged chunkless level, confirmed: no
                        # chunk keys among the probe's spread candidates.
                        emit("CHUNK_LEVEL_NO_CHUNKS", "info", root,
                             level, "",
                             "level holds no stored chunks (audit: "
                             "has_chunks=false; probe: no keys among 9 "
                             "spread candidates)", 0)
                    else:
                        # Sparse level the spread sampling couldn't cover:
                        # not evidence of absence, reported as a coverage
                        # gap rather than a finding.
                        emit("CHUNK_LEVEL_NO_SAMPLES", "info", root,
                             level, "",
                             "no chunk keys among 9 spread candidates; "
                             "sparse level not coverable by spread "
                             "sampling", 0)
                    continue
                for s in samples:
                    bytes_total += s.bytes_fetched
                    if s.status == "populated":
                        emit("CHUNK_SAMPLE_POPULATED", "info", s.root,
                             s.level, ".".join(map(str, s.chunk_index)),
                             s.detail, s.bytes_fetched)
                    elif s.status == "empty":
                        emit("CHUNK_SAMPLE_EMPTY", "info", s.root, s.level,
                             ".".join(map(str, s.chunk_index)), s.detail,
                             s.bytes_fetched)
                    elif s.status == "missing":
                        emit("CHUNK_SAMPLE_MISSING", "info", s.root, s.level,
                             ".".join(map(str, s.chunk_index)), s.detail,
                             s.bytes_fetched)
                    elif s.status == "absent":
                        emit("CHUNK_SAMPLE_ABSENT", "info", s.root, s.level,
                             ".".join(map(str, s.chunk_index)), s.detail,
                             s.bytes_fetched)
                    elif s.status == "undecodable":
                        emit("CHUNK_UNDECODEABLE", "low", s.root, s.level,
                             ".".join(map(str, s.chunk_index)), s.detail,
                             s.bytes_fetched)
                    else:
                        emit("CHUNK_FETCH_ERROR", "low", s.root, s.level,
                             ".".join(map(str, s.chunk_index)), s.detail,
                             s.bytes_fetched)
                # Only *present* chunks count toward the all-empty verdict;
                # missing inner chunks legitimately read as fill (masked).
                decodable = [s for s in samples
                             if s.status in ("populated", "empty")]
                if decodable and all(s.status == "empty" for s in decodable):
                    levels_all_empty.append((root, level))
                    emit("CHUNK_SAMPLE_ALL_EMPTY", "medium", root, level,
                         "",
                         f"all {len(decodable)} sampled chunks decode to "
                         f"fill_value; human review needed", 0)

        summary = {
            "roots_scanned": len(roots),
            "levels_scanned": levels_scanned,
            "levels_all_empty": [f"{r} L{l}" for r, l in levels_all_empty],
            "n_levels_all_empty": len(levels_all_empty),
            "bytes_fetched": bytes_total,
            "by_code": dict(codes.most_common()),
        }
        write_json(sm_path, summary)
        man.set("summary", summary)
        print("\n=== SUMMARY ===")
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
