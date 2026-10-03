#!/usr/bin/env python3
"""Cross-cut the frozen S3 pyramid audit by the exact 2027 Grand Prize CT volumes."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "prize-manifest.json"
PYRAMIDS = ROOT / "2026-09-29-s3/audit_pyramid.pyramids.jsonl"
OUT = HERE / "summary.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in PYRAMIDS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    targets = []
    for target in manifest["targets"]:
        matches = [
            row for row in rows
            if row["root"].startswith(f'{target["scroll"]}/volumes/')
            and f'/{target["volume_id"]}-' in row["root"]
        ]
        targets.append({
            "scroll": target["scroll"],
            "volume_id": str(target["volume_id"]),
            "matches": len(matches),
            "roots": [{
                "root": row["root"],
                "zarr_format": row["zarr_format"],
                "n_levels": row["n_levels"],
                "n_levels_present": row["n_levels_present"],
                "levels_no_chunks": row.get("levels_no_chunks", []),
                "levels_chunks_unknown": row.get("levels_chunks_unknown", []),
                "errors": row.get("errors", []),
                "n_findings": row.get("n_findings", 0),
                "codes": row.get("codes", []),
            } for row in matches],
        })

    exact = [t for t in targets if t["matches"] == 1]
    out = {
        "schema_version": 1,
        "diagnostic": "2027-grand-prize-exact-ct-preflight",
        "as_of": "2026-10-02",
        "audit_as_of": "2026-09-29",
        "rule": (
            "Match the exact prize-listed scroll and volume_id to the frozen S3 pyramid audit. "
            "Same-scroll substitute scans do not count."
        ),
        "sources": {
            "prize_manifest": "prize-manifest.json",
            "s3_pyramid_audit": "../2026-09-29-s3/audit_pyramid.pyramids.jsonl",
        },
        "totals": {
            "eligible_targets": len(targets),
            "exact_roots_found": len(exact),
            "ambiguous_or_missing": len(targets) - len(exact),
            "roots_with_zero_findings": sum(t["roots"][0]["n_findings"] == 0 for t in exact),
            "roots_with_all_declared_levels_present": sum(
                t["roots"][0]["n_levels"] == t["roots"][0]["n_levels_present"] for t in exact
            ),
            "roots_with_no_chunkless_levels": sum(
                not t["roots"][0]["levels_no_chunks"] for t in exact
            ),
            "roots_with_no_unknown_chunk_presence": sum(
                not t["roots"][0]["levels_chunks_unknown"] for t in exact
            ),
        },
        "targets": targets,
        "claim_boundary": [
            "This is a header/chunk-presence cross-cut of the frozen S3 audit; it does not decode all CT content.",
            "Zero findings does not certify semantic voxel correctness, scan quality, surface identity, flattening quality, or ink.",
            "The result is dated to the 2026-09-29 S3 audit and should be re-run before a final submission freeze.",
        ],
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
