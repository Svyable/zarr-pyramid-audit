#!/usr/bin/env python3
"""
gate.py -- publish-time metadata gate for OME-Zarr multiscale pyramids.

Villa #1760 showed that structural pyramid defects (missing levels,
header-only levels, scale/shape mismatches) reach published data because
nothing checks them *before* publication. This is the check that would have
caught them: point it at the roots you are about to publish and it fails
closed on any structural defect at or above the chosen severity.

Header-only: a few KB per pyramid regardless of array size. Typical usage in
CI or a publish script:

    python bin/gate.py --base s3://my-bucket/publish/ \\
        --roots publish_manifest.jsonl --fail-on high

Exit codes: 0 = all roots clean, 1 = gate failed (defects or unreadable
roots), 2 = usage error.

Usage:
    python bin/gate.py --base https://dl.ash2txt.org/ --root <path> [--root ...]
    python bin/gate.py --base s3://bucket/ --roots roots.jsonl --fail-on medium
    python bin/gate.py --base https://dl.ash2txt.org/ --roots roots.jsonl \\
        --format github --out gate-report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util as _ilu

_ap_spec = _ilu.spec_from_file_location(
    "audit_pyramid",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_pyramid.py"))
_ap = _ilu.module_from_spec(_ap_spec)
_ap_spec.loader.exec_module(_ap)
INFO_CODES, SEVERITY, audit_one, load_roots = (
    _ap.INFO_CODES, _ap.SEVERITY, _ap.audit_one, _ap.load_roots)

from zpa.httpstore import open_store                                       # noqa: E402
from zpa.pool import parallel_map                                          # noqa: E402
from zpa.zarrmeta import read_pyramid                                      # noqa: E402

SEV_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True,
                    help="store base URL (http(s):// or s3://)")
    ap.add_argument("--roots", help="JSONL from discover_zarr.py")
    ap.add_argument("--root", action="append", default=[],
                    help="explicit root (repeatable)")
    ap.add_argument("--fail-on", default="high",
                    choices=["high", "medium", "low", "info"],
                    help="fail the gate on findings at or above this severity "
                         "(default: high)")
    ap.add_argument("--ignore-unreadable", action="store_true",
                    help="do not fail the gate when a root cannot be read at "
                         "all (default: unreadable roots fail the gate)")
    ap.add_argument("--format", default="text", choices=["text", "github"],
                    help="'github' emits ::error/::warning workflow annotations")
    ap.add_argument("--out", default=None,
                    help="write a JSON gate report to this path")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--max-rps", type=float, default=None)
    ap.add_argument("--no-chunk-presence", action="store_true",
                    help="skip the one-listing-per-level LEVEL_NO_CHUNKS probe")
    args = ap.parse_args(argv)
    if not args.roots and not args.root:
        ap.error("need --roots <jsonl> or at least one --root <path>")
    return args


def check_one(store, root: str, args) -> dict:
    """Audit a single root; return its gate verdict."""
    try:
        pm = read_pyramid(store, root, check_chunks=not args.no_chunk_presence)
        findings, _, _ = audit_one(pm)
    except Exception as e:  # noqa: BLE001 -- a gate must report, not crash
        return {"root": root, "verdict": "unreadable",
                "fail": not args.ignore_unreadable,
                "findings": [{"code": "GATE_UNREADABLE", "severity": "high",
                              "level": "", "detail": f"{type(e).__name__}: {e}"}]}
    threshold = SEV_ORDER[args.fail_on]
    failing = [f for f in findings
               if SEV_ORDER.get(f["severity"], 0) >= threshold]
    info = [f for f in findings if f["code"] in INFO_CODES]
    return {"root": root,
            "verdict": "fail" if failing else "pass",
            "fail": bool(failing),
            "findings": failing,
            "informational": [{"code": f["code"], "detail": f["detail"]}
                              for f in info]}


def emit_text(results: list[dict]) -> None:
    for r in results:
        if r["verdict"] == "pass":
            extra = ""
            if r.get("informational"):
                codes = sorted({i["code"] for i in r["informational"]})
                extra = f" [{','.join(codes)}]"
            print(f"PASS  {r['root']}{extra}")
        elif r["verdict"] == "unreadable":
            print(f"ERROR {r['root']}: {r['findings'][0]['detail']}")
        else:
            print(f"FAIL  {r['root']}:")
            for f in r["findings"]:
                lvl = f" level={f['level']}" if f["level"] else ""
                print(f"      [{f['severity']}] {f['code']}{lvl}: {f['detail']}")


def emit_github(results: list[dict]) -> None:
    for r in results:
        for f in r["findings"]:
            kind = "error" if f["severity"] == "high" else "warning"
            lvl = f" level={f['level']}" if f["level"] else ""
            # single line; GitHub annotations take %0A for newlines
            detail = f["detail"].replace("\n", "%0A")
            print(f"::{kind} title={f['code']} {r['root']}{lvl}::{detail}")
        if r["verdict"] == "unreadable":
            d = r["findings"][0]["detail"].replace("\n", "%0A")
            print(f"::error title=GATE_UNREADABLE {r['root']}::{d}")


def main(argv=None) -> int:
    args = parse_args(argv)
    store = open_store(args.base, timeout=args.timeout, max_rps=args.max_rps)
    roots = load_roots(args)
    if not roots:
        print("no roots to gate", file=sys.stderr)
        return 2

    results = []
    for res in parallel_map(lambda rt: check_one(store, rt, args), roots,
                            workers=args.workers, label="gating"):
        if not res.ok:
            results.append({"root": res.item, "verdict": "unreadable",
                            "fail": not args.ignore_unreadable,
                            "findings": [{"code": "GATE_UNREADABLE",
                                          "severity": "high", "level": "",
                                          "detail": res.error}]})
        else:
            results.append(res.value)

    results.sort(key=lambda r: (0 if r["fail"] else 1, r["root"]))
    if args.format == "github":
        emit_github(results)
    else:
        emit_text(results)

    n_fail = sum(1 for r in results if r["fail"])
    n_pass = len(results) - n_fail
    print(f"\ngate: {n_pass} pass, {n_fail} fail out of {len(results)} roots "
          f"(threshold: {args.fail_on}+)")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"base": args.base, "fail_on": args.fail_on,
                       "n_roots": len(results), "n_pass": n_pass,
                       "n_fail": n_fail, "results": results},
                      fh, indent=2)

    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
