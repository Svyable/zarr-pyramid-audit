#!/usr/bin/env python3
"""Call the public API and forward evidence into a downstream pipeline.

    python examples/python_api.py                      # offline, fixture corpus
    python examples/python_api.py s3://vesuvius-challenge-open-data/ <root> ...

The stable surface (schema_version 1.2.0):

  zpa.httpstore.open_store(base)  -> store for http(s)://, s3://, file:// or a path
  zpa.report.audit_root(store, root) -> report dict; never raises, never clean on error
  zpa.report.consumer_verdict(report) -> recommended action for the integrity state
  zpa/data/audit-report.schema.json   -> JSON Schema for the report

ZPA produces evidence; the consuming workflow owns the decision. This example
implements one policy -- drop FAIL and UNKNOWN, down-weight WARN -- and hands
the rest to a ranking step, keeping the evidence attached to every decision.
"""
from __future__ import annotations

import json
import os
import sys

from zpa.httpstore import open_store
from zpa.report import audit_root, consumer_verdict, validate_report

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE = os.path.join(HERE, os.pardir, "fixtures", "zarr")
DEFAULT_ROOTS = ["clean_v2.zarr", "fill_drift.zarr", "level_no_chunks.zarr",
                 "root_absent.zarr"]

# The consumer's policy, not ZPA's: weight per integrity state.
WEIGHT = {"PASS": 1.0, "WARN": 0.5, "UNKNOWN": 0.0, "FAIL": 0.0}


def triage(base: str, roots: list[str]) -> list[dict]:
    store = open_store(base)
    decisions = []
    for root in roots:
        report = audit_root(store, root)
        assert not validate_report(report), "report violates the schema"
        decisions.append({
            "root": root,
            "integrity": report["integrity"],
            "verdict": consumer_verdict(report),
            "weight": WEIGHT[report["integrity"]],
            # keep the evidence with the decision, so it can be audited later
            "evidence": [
                {k: f[k] for k in ("code", "severity", "level", "evidence_state")}
                for f in report["findings"]
            ],
            "schema_version": report["schema_version"],
        })
    return decisions


def main(argv: list[str]) -> int:
    base, roots = (argv[0], argv[1:]) if argv else (DEFAULT_BASE, DEFAULT_ROOTS)
    decisions = triage(base, roots)
    queue = sorted((d for d in decisions if d["weight"] > 0),
                   key=lambda d: -d["weight"])
    print(json.dumps({"train_queue": [d["root"] for d in queue],
                      "decisions": decisions}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
