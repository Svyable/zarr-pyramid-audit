"""Strict regression diff between two zpa-audit runs.

    python artifacts/2026-10-01-s3-regression/regression_diff.py \
        --baseline artifacts/2026-09-29-s3 --current artifacts/2026-10-01-s3-regression

Each directory needs audit_pyramid.findings.csv and audit_pyramid.pyramids.jsonl
(and optionally discover_zarr.roots.jsonl). A finding is identified by every
field the CSV records: (code, severity, root, level, detail, observed,
expected), the key the 2026-09-29 dl regression used. Findings on roots the
baseline did not audit are reported separately as "on new roots", never as
regressions; roots the current run did not audit are listed, so a dropped
root can never read as a fixed defect.
"""
import argparse
import csv
import json
import os
from collections import Counter

FIELDS = ("code", "severity", "root", "level", "detail", "observed", "expected")


def findings(d):
    with open(os.path.join(d, "audit_pyramid.findings.csv"), newline="", encoding="utf-8") as fh:
        return {tuple(row[f] for f in FIELDS) for row in csv.DictReader(fh)}


def audited_roots(d):
    with open(os.path.join(d, "audit_pyramid.pyramids.jsonl"), encoding="utf-8") as fh:
        return {json.loads(line)["root"].rstrip("/") for line in fh if line.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--json", help="also write the diff as JSON here")
    a = ap.parse_args(argv)

    base_f, cur_f = findings(a.baseline), findings(a.current)
    base_r, cur_r = audited_roots(a.baseline), audited_roots(a.current)
    common = base_r & cur_r
    in_common = lambda fs: {f for f in fs if f[2].rstrip("/") in common}
    fixed = sorted(in_common(base_f) - cur_f)
    new = sorted(in_common(cur_f) - base_f)
    unchanged = in_common(base_f) & cur_f
    on_new_roots = sorted(f for f in cur_f if f[2].rstrip("/") not in base_r)

    out = {
        "baseline": a.baseline, "current": a.current,
        "roots": {"baseline": len(base_r), "current": len(cur_r), "common": len(common),
                  "added": sorted(cur_r - base_r), "dropped": sorted(base_r - cur_r)},
        "findings_in_common_roots": {"fixed": len(fixed), "new": len(new),
                                     "unchanged": len(unchanged)},
        "defective_roots": {"baseline": len({f[2] for f in base_f if f[1] != "info"}),
                            "current": len({f[2] for f in cur_f if f[1] != "info"})},
        "fixed": [dict(zip(FIELDS, f)) for f in fixed],
        "new": [dict(zip(FIELDS, f)) for f in new],
        "on_new_roots": [dict(zip(FIELDS, f)) for f in on_new_roots],
        "on_new_roots_by_code": dict(Counter(f[0] for f in on_new_roots)),
    }
    r = out["roots"]
    print(f"roots: baseline {r['baseline']}, current {r['current']}, common {r['common']}, "
          f"added {len(r['added'])}, dropped {len(r['dropped'])}")
    c = out["findings_in_common_roots"]
    print(f"findings on common roots: fixed {c['fixed']}, new {c['new']}, unchanged {c['unchanged']}")
    print(f"defective roots (non-info finding): baseline {out['defective_roots']['baseline']}, "
          f"current {out['defective_roots']['current']}")
    print(f"findings on added roots: {len(on_new_roots)} {out['on_new_roots_by_code']}")
    for label in ("fixed", "new"):
        for f in out[label]:
            print(f"  {label}: {f['code']} {f['root']} level={f['level']}")
    for root in r["dropped"]:
        print(f"  dropped root: {root}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
