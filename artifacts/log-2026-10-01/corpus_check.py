# Run from the repo root: python artifacts/log-2026-10-01/corpus_check.py
# Counts the conditions the new OME-NGFF conformance checks look for, in the
# committed 2026-09-29 S3 audit artifacts (header-only data, no network).
import json
d = "artifacts/2026-09-29-s3/audit_pyramid"
lv = [json.loads(l) for l in open(d + ".levels.jsonl") if l.strip() and json.loads(l).get("present")]
py = [json.loads(l) for l in open(d + ".pyramids.jsonl") if l.strip()]
print("present levels:", len(lv))
print("no declared scale:", sum(1 for r in lv if not r.get("declared_scale")))
print("scale length != ndim:", sum(1 for r in lv if r.get("declared_scale") and r.get("shape") and len(r["declared_scale"]) != len(r["shape"])))
print("pyramids:", len(py))
print("duplicate axis names:", sum(1 for r in py if len(set(r.get("axes") or [])) != len(r.get("axes") or [])))
print("axes length outside 2..5 (non-empty):", sum(1 for r in py if r.get("axes") and not 2 <= len(r["axes"]) <= 5))
