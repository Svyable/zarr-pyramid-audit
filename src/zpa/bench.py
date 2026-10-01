#!/usr/bin/env python3
"""
bench.py -- measure what an audit costs: latency, bytes, and request counts.

The project trades confidence against network cost: a header-only audit
reads a few KB per pyramid, a sampled chunk probe reads more and proves
more. This tool makes that trade-off measurable per root, on any store.

For each root it runs, on a fresh store instance:

  1. the header-only audit (``read_pyramid`` + ``audit_one``, chunk-presence
     listings on, as ``zpa-audit``/``zpa-gate`` run it), then
  2. the sampled chunk-content probe (``probe_level``, K samples per
     present level) for unsharded v2/v3 levels.

It counts calls at the store API boundary: metadata reads (JSON objects),
directory listings, HEAD/existence probes, chunk reads (full or ranged),
and the payload bytes those calls returned. Payload bytes are what the
auditor received, not wire bytes: HTTP headers, TLS, S3 ListObjects
responses and any client-side read-ahead are not included. Sharded v3
levels are probed through other code paths (volcomp byte ranges or
zarr-python windows) and are reported as ``not_measured`` here, never as
zero cost.

Outputs (into --out-dir; existing files are backed up, never overwritten):
    bench.jsonl          one record per root
    bench.summary.md     the markdown table used in the README
    bench.manifest.json  provenance

Usage:
    AWS_ENDPOINT_URL_S3=https://s3.us-east-1.amazonaws.com \\
    zpa-bench --base s3://vesuvius-challenge-open-data/ \\
        --root <root.zarr> [--root ...] --samples-per-level 3 --out-dir tmp/bench
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

from zpa.audit_pyramid import audit_one
from zpa.chunkscan import classify_level, probe_level
from zpa.httpstore import open_store
from zpa.report import build_report
from zpa.runio import JsonlWriter, RunManifest, safe_open
from zpa.zarrmeta import read_pyramid

# store method -> counter category
_CATEGORY = {
    "json_evidence": "metadata_reads",
    "list_dir_evidence": "listings",
    "head": "existence_probes",
    "get_range": "chunk_reads",
    "get_suffix": "chunk_reads",
}


class CountingStore:
    """Instrument a store instance in place and count calls + payload bytes.

    Patching the instance (not wrapping it) keeps internal ``self.get``
    calls counted too, so bytes read by ``json_evidence`` and listings are
    attributed to the call that caused them.
    """

    def __init__(self, store):
        self.store = store
        self.calls: Counter = Counter()
        self.bytes: Counter = Counter()
        self._active: list[str] = []
        for name, category in _CATEGORY.items():
            self._wrap(name, category)
        self._wrap_get()

    def _wrap(self, name, category):
        original = getattr(self.store, name)

        def wrapper(*args, **kwargs):
            self.calls[category] += 1
            self._active.append(category)
            try:
                result = original(*args, **kwargs)
            finally:
                self._active.pop()
            if category == "chunk_reads" and isinstance(result, (bytes, bytearray)):
                self.bytes[category] += len(result)
            return result

        setattr(self.store, name, wrapper)

    def _wrap_get(self):
        original = self.store.get

        def get(*args, **kwargs):
            outer = self._active[-1] if self._active else None
            if outer is None:
                self.calls["chunk_reads"] += 1
            data = original(*args, **kwargs)
            # A ranged read that is implemented via get() (LocalStore) is
            # counted by its wrapper, at the size it returned.
            if outer != "chunk_reads":
                self.bytes[outer or "chunk_reads"] += len(data)
            return data

        self.store.get = get

    def snapshot(self) -> dict:
        return {"calls": dict(self.calls), "bytes": dict(self.bytes),
                "requests": int(sum(self.calls.values())),
                "payload_bytes": int(sum(self.bytes.values()))}

    def reset(self):
        self.calls.clear()
        self.bytes.clear()


def bench_root(base: str, root: str, *, samples_per_level: int = 3,
               store_kw=None) -> dict:
    store = open_store(base, **(store_kw or {}))
    counter = CountingStore(store)

    t0 = time.perf_counter()
    pm = read_pyramid(store, root)
    findings, level_recs, pyr = audit_one(pm)
    report = build_report(pm, findings=findings, pyramid_record=pyr)
    header_s = time.perf_counter() - t0
    header = counter.snapshot()

    counter.reset()
    statuses: Counter = Counter()
    scan_codes: Counter = Counter()
    not_measured = []
    t1 = time.perf_counter()
    for rec in level_recs:
        if not rec.get("present") or not rec.get("shape") or not rec.get("chunks"):
            continue
        if (rec.get("compressor") or "").lower() == "sharding_indexed":
            not_measured.append(str(rec["level"]))
            continue
        samples = probe_level(store, root, rec, samples_per_level=samples_per_level)
        statuses.update(s.status for s in samples)
        level_findings, _ = classify_level(root, str(rec["level"]),
                                           rec.get("has_chunks"), samples,
                                           n_candidates=samples_per_level * 3)
        scan_codes.update(f["code"] for f in level_findings
                          if f["severity"] != "info"
                          or f["code"].startswith("CHUNK_LEVEL"))
    probe_s = time.perf_counter() - t1
    probe = counter.snapshot()

    return {
        "root": root,
        "base": base,
        "zarr_format": pm.zarr_format,
        "n_levels": len(pm.levels),
        "integrity": report["integrity"],
        "codes": sorted({f["code"] for f in report["findings"]}),
        "header": {"seconds": round(header_s, 3), **header},
        "probe": {"seconds": round(probe_s, 3), **probe,
                  "samples_per_level": samples_per_level,
                  "statuses": dict(statuses),
                  "codes": dict(scan_codes),
                  "levels_not_measured": not_measured},
    }


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def markdown_table(records: list[dict]) -> str:
    lines = [
        "| root | levels | header audit: time · requests (meta/list/head) · payload | "
        "findings | chunk probe: time · reads · payload | probe result |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        h, p = r["header"], r["probe"]
        hc = h["calls"]
        name = r["root"].rstrip("/").split("/")[-1]
        findings = ", ".join(r["codes"]) or "none"
        if p["levels_not_measured"] and not p["statuses"]:
            probe_cost = "not measured (sharded v3)"
            probe_res = "—"
        else:
            reads = p["calls"].get("chunk_reads", 0)
            heads = p["calls"].get("existence_probes", 0)
            probe_cost = (f"{p['seconds']:.2f} s · {reads} reads + {heads} HEAD · "
                          f"{_fmt_bytes(p['payload_bytes'])}")
            parts = [", ".join(f"{k} {v}" for k, v in sorted(p["statuses"].items())),
                     ", ".join(sorted(p["codes"]))]
            probe_res = "; ".join(x for x in parts if x) or "—"
        lines.append(
            f"| `{name}` | {r['n_levels']} | {h['seconds']:.2f} s · {h['requests']} "
            f"({hc.get('metadata_reads', 0)}/{hc.get('listings', 0)}/"
            f"{hc.get('existence_probes', 0)}) · {_fmt_bytes(h['payload_bytes'])} | "
            f"{findings} ({r['integrity']}) | {probe_cost} | {probe_res} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--root", action="append", default=[], required=True,
                    help="root to measure (repeatable)")
    ap.add_argument("--samples-per-level", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--out-dir", default="tmp/bench")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)

    store_kw = {} if args.base.startswith("s3://") else {"timeout": args.timeout}
    records = []
    jl = os.path.join(args.out_dir, "bench.jsonl")
    md = os.path.join(args.out_dir, "bench.summary.md")
    with RunManifest("bench", args.out_dir) as man, JsonlWriter(jl) as w:
        man.set("base", args.base)
        man.set("roots", args.root)
        man.set("samples_per_level", args.samples_per_level)
        for root in args.root:
            rec = bench_root(args.base, root,
                             samples_per_level=args.samples_per_level,
                             store_kw=store_kw)
            records.append(rec)
            w.write(rec)
            print(json.dumps({k: rec[k] for k in ("root", "integrity", "codes")}),
                  file=sys.stderr)
        with safe_open(md, "w") as fh:
            fh.write(markdown_table(records))
        man.add_output(jl, "per-root measurements")
        man.add_output(md, "markdown table")
    print(markdown_table(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
