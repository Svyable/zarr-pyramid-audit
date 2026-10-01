"""Compare per-level metadata between two zpa-audit levels.jsonl files.

    python artifacts/2026-10-01-s3-regression/compare_levels.py \
        artifacts/2026-09-29-s3/audit_pyramid.levels.jsonl tmp/g1/audit/audit_pyramid.levels.jsonl

The 2026-10-01 levels.jsonl (3.2 MB) is not committed; re-run the audit in
README.md to regenerate it. Prints the levels whose stored metadata or chunk
presence changed, and the chunk-evidence states of the current run. A field
is compared only where both runs recorded it: older tool versions did not
write every field (the 2026-09-29 run has no `zarr_format`), and a missing
field is reported as not comparable, never as a change.
"""
import json
import sys
from collections import Counter

FIELDS = ("present", "shape", "chunks", "dtype", "fill_value", "compressor",
          "dimension_separator", "zarr_format", "has_chunks", "top_entries")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return {(r["root"], r["level"]): r for r in map(json.loads, fh) if r}


old, new = load(sys.argv[1]), load(sys.argv[2])
common = old.keys() & new.keys()
comparable = [f for f in FIELDS
              if all(f in old[k] and f in new[k] for k in common)]
skipped = [f for f in FIELDS if f not in comparable]
changed = [k for k in common if any(old[k][f] != new[k][f] for f in comparable)]
print(f"levels: baseline {len(old)}, current {len(new)}, "
      f"only baseline {len(old.keys() - new.keys())}, only current {len(new.keys() - old.keys())}")
print(f"levels with a changed field ({', '.join(comparable)}): {len(changed)}")
print(f"not comparable (missing from a run): {', '.join(skipped) or 'none'}")
for k in sorted(changed):
    print("  changed:", *k)
print("current chunk evidence:", dict(Counter(r.get("chunk_evidence_state") for r in new.values())),
      dict(Counter(r.get("chunk_evidence_reason") for r in new.values()
                   if r.get("chunk_evidence_state") != "PRESENT")))
