#!/usr/bin/env python3
"""build_known_defects.py -- compile data/known-defects.json from audit artifacts.

The kill list: every pyramid with a confirmed structural (high-severity)
finding, plus low-severity anomalies, across both public stores. Generated
from the audit CSVs so it never drifts from the evidence; re-run after each
audit and diff.
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

REPO = os.environ.get("ZPA_REPO", os.getcwd())
ART = REPO + "/artifacts"

UPSTREAM = {
    # root suffix -> villa issue
    "1.129um-0.22m-59keV-volume-20260521123630-L1.zarr": "#1892",
    "1-voxel-sheet_slices-closed.zarr": "#1755",
    "3336_predictions.zarr": "#1756",
}


def load_findings(csv_path, store):
    roots = defaultdict(list)
    with open(csv_path) as fh:
        for r in csv.DictReader(fh):
            if r["severity"] == "info":
                continue
            roots[r["root"]].append(r)
    return store, roots


def main():
    entries = []
    for csv_path, store, first_seen in [
        (f"{ART}/2026-09-29-s3/audit_pyramid.findings.csv",
         "s3://vesuvius-challenge-open-data", "2026-09-29"),
        (f"{ART}/2026-09-29-dl-regression/audit_pyramid.findings.csv",
         "https://dl.ash2txt.org", "2026-09-29"),
    ]:
        _, roots = load_findings(csv_path, store)
        for root in sorted(roots):
            rows = roots[root]
            sevs = {r["severity"] for r in rows}
            sev = "high" if "high" in sevs else "low"
            codes = sorted({r["code"] for r in rows})
            issue = next((v for suf, v in UPSTREAM.items()
                          if root.endswith(suf)), None)
            entries.append({
                "root": root,
                "store": store,
                "severity": sev,
                "finding_codes": codes,
                "first_seen": first_seen,
                "last_confirmed": "2026-09-29",
                "status": "open",
                "upstream_issue": ("villa " + issue) if issue else None,
                "evidence": ("artifacts/2026-09-29-s3/SILENT_ZEROS.md"
                             if store.startswith("s3") and
                             root.endswith("L1.zarr")
                             else "artifacts/2026-09-29-dl-regression/"),
            })
    entries.sort(key=lambda e: (e["store"], e["severity"] != "high",
                                e["root"]))
    doc = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_entries": len(entries),
        "note": ("Machine-readable kill list of confirmed pyramid defects. "
                 "'open' means still present at last_confirmed; nothing in "
                 "this list has been observed repaired."),
        "defects": entries,
    }
    out = REPO + "/data/known-defects.json"
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    print(f"wrote {out} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
