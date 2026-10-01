"""Every number quoted in this directory's README, computed from the run.

    python artifacts/2026-10-01-s3-tifxyz/summarize.py

Reads tifxyz.reports.jsonl (one report per surface, written by zpa-tifxyz)
and discover_zarr.surfaces.jsonl, and prints the figures as markdown.
"""
import json
import os
import statistics
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


reports = load("tifxyz.reports.jsonl")
surfaces = load("discover_zarr.surfaces.jsonl")
codes = Counter(f["code"] for r in reports for f in r["findings"])
per_code_surfaces = Counter(c for r in reports for c in {f["code"] for f in r["findings"]})
checked = [r for r in reports if r["surface"]["content_checked"]]
decoders = Counter(v for r in checked for v in set(r["surface"]["decoders"].values()))
vf = [r["surface"]["valid_fraction"] for r in checked]


def bbox_kind(r):
    f = next(f for f in r["findings"] if f["code"] == "TIFXYZ_BBOX_MISMATCH")
    out = r["surface"].get("bbox_points_outside", 0)
    leak = "-1 invalid marker" in f["detail"]
    return ("points outside" if out else "loose") + (" + -1 leak" if leak else "")


bbox = [r for r in reports if "TIFXYZ_BBOX_MISMATCH" in {f["code"] for f in r["findings"]}]
neg = [r for r in reports if "TIFXYZ_NEGATIVE_COORDINATE" in {f["code"] for f in r["findings"]}]

print(f"- surfaces discovered: {len(surfaces)} "
      f"({dict(Counter(s['detected_by'] for s in surfaces))})")
print(f"- surfaces audited: {len(reports)}; integrity "
      f"{dict(Counter(r['integrity'] for r in reports))}")
print(f"- content tier ran: {len(checked)} "
      f"(decoders: {dict(decoders)}); skipped: {len(reports) - len(checked)}")
print(f"- valid fraction over content-checked surfaces: min {min(vf):.3f}, "
      f"median {statistics.median(vf):.3f}, max {max(vf):.3f}")
print("\n| code | surfaces | findings |\n|---|---|---|")
for code, n in per_code_surfaces.most_common():
    print(f"| `{code}` | {n} | {codes[code]} |")
print("\nTIFXYZ_BBOX_MISMATCH by kind:", dict(Counter(bbox_kind(r) for r in bbox)))
print("TIFXYZ_BBOX_MISMATCH by scroll:",
      dict(Counter(r["root"].split("/")[0] for r in bbox)))
print("TIFXYZ_NEGATIVE_COORDINATE by scroll:",
      dict(Counter(r["root"].split("/")[0] for r in neg)))
for r in sorted(bbox, key=lambda r: -r["surface"].get("bbox_points_outside", 0))[:5]:
    if r["surface"].get("bbox_points_outside"):
        print(f"  outside: {r['root']}  {r['surface']['bbox_points_outside']} points")
