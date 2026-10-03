"""Compare xzarrguard and ZPA on the subset of committed Zarr v3 fixtures.

This is deliberately a completeness comparison, not an accuracy leaderboard.
xzarrguard is a Zarr v3 completeness checker; ZPA covers a broader set of
metadata, evidence and content semantics. Only fixtures with a root zarr.json
are included.

Requires Python 3.12+:

    pip install -e .
    pip install -r fixtures/requirements-completeness.txt
    python fixtures/compare_xzarrguard.py --out-dir artifacts/<date>-xzarrguard-comparison
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import compare_baselines as baseline  # noqa: E402
import corpus  # noqa: E402


def is_v3_fixture(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "zarr.json"))


def xzarrguard_(path: str) -> dict:
    import xzarrguard

    try:
        report = xzarrguard.check_store(path)
    except Exception as exc:
        return {
            "outcome": "error",
            "detail": f"{type(exc).__name__}: {exc}",
            "ok": None,
            "errors": [],
            "expected_chunks": None,
            "missing_unexpected": None,
            "missing_allowed": None,
            "manifest_issues": None,
        }

    data = report.to_dict()
    variables = data.get("variables") or {}
    expected = sum(int(v.get("expected_chunks", 0)) for v in variables.values())
    missing_unexpected = sum(len(v.get("missing_unexpected") or [])
                             for v in variables.values())
    missing_allowed = sum(len(v.get("missing_allowed") or [])
                          for v in variables.values())
    manifest_issues = sum(
        len(v.get("stale_manifest") or [])
        + len(v.get("manifest_key_mismatch") or [])
        + len(v.get("manifest_out_of_bounds") or [])
        for v in variables.values()
    )
    errors = [str(e) for e in data.get("errors") or []]
    return {
        "outcome": "complete" if data.get("ok") else "incomplete",
        "detail": "; ".join(errors) if errors else "",
        "ok": bool(data.get("ok")),
        "errors": errors,
        "expected_chunks": expected,
        "missing_unexpected": missing_unexpected,
        "missing_allowed": missing_allowed,
        "manifest_issues": manifest_issues,
    }


def run() -> list[dict]:
    rows = []
    for name, prop, _ in corpus.ZARR_CASES:
        path = os.path.join(corpus.ZARR_DIR, f"{name}.zarr")
        if not is_v3_fixture(path):
            continue
        rows.append({
            "fixture": name,
            "property": prop,
            "truth": baseline.GROUND_TRUTH[name],
            "xzarrguard": xzarrguard_(path),
            "zpa": baseline.zpa(name),
        })
    return rows


def markdown(rows: list[dict], versions: dict) -> str:
    lines = [
        "# Zarr v3 completeness comparison",
        "",
        "This table is per-fixture evidence, not an aggregate accuracy score.",
        "",
        "| fixture | fixture class | xzarrguard | expected chunks | unexpected missing | allowed missing | manifest issues | ZPA integrity / codes |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        x = row["xzarrguard"]
        z = row["zpa"]
        if x["outcome"] == "error":
            xcell = f"error: {x['detail']}"
            expected = missing = allowed = manifest = "—"
        else:
            xcell = x["outcome"]
            expected = str(x["expected_chunks"])
            missing = str(x["missing_unexpected"])
            allowed = str(x["missing_allowed"])
            manifest = str(x["manifest_issues"])
        lines.append(
            f"| `{row['fixture']}` | {row['truth']} | {xcell} | {expected} | "
            f"{missing} | {allowed} | {manifest} | "
            f"{z['integrity']} {', '.join(z['codes']) or '—'} |"
        )
    lines += [
        "",
        "Versions: " + ", ".join(f"{k} {v}" for k, v in versions.items()),
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)

    import xzarrguard
    from importlib.metadata import version

    versions = {
        "xzarrguard": xzarrguard.__version__,
        "zarr-pyramid-audit": version("zarr-pyramid-audit"),
        "fixture corpus": corpus.CORPUS_VERSION,
    }
    rows = run()
    os.makedirs(args.out_dir, exist_ok=True)

    with open(os.path.join(args.out_dir, "comparison.json"), "w", encoding="utf-8") as fh:
        json.dump({"versions": versions, "rows": rows}, fh, indent=2, sort_keys=True)
        fh.write("\n")

    md = markdown(rows, versions)
    with open(os.path.join(args.out_dir, "comparison.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
