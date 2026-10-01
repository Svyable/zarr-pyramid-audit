"""
report.py -- the versioned, machine-readable audit report (public contract).

``audit_one`` returns raw findings. Downstream consumers (ScrolIQ, CI gates,
training pipelines) need more than that: they need to know whether the
*evidence* behind a clean result was actually observed. This module wraps
one audit into a schema-versioned document validated by
``zpa/data/audit-report.schema.json``.

The contract, in one paragraph:

  * ``integrity`` is the summary a consumer branches on:
      FAIL    -- at least one ``high`` finding (do not train / publish)
      UNKNOWN -- no ``high`` finding, but no clean verdict can be issued:
                 required evidence could not be observed (timeout, 403,
                 5xx...), or there was nothing to audit (the root is
                 confirmed absent or an empty directory)
      WARN    -- a ``medium`` finding, everything required was observed
      PASS    -- nothing above ``low``, everything required was observed
  * UNKNOWN is never PASS. A clean-looking result built on unobserved
    evidence is the failure this project exists to prevent.
  * ``coverage`` says which optional evidence (chunk-presence listings)
    was not observed. Those gaps do not change ``integrity``; they are
    reported so nobody mistakes "not checked" for "checked and fine".
  * Every finding carries the ``evidence_state`` it rests on:
      PRESENT -- derived from metadata that was read successfully
      ABSENT  -- derived from confirmed absence (404, empty listing that
                 provably shows the header)
      UNKNOWN -- the attempted observation failed

ZPA produces evidence; consuming workflows own the decision policy.
``RECOMMENDED_CONSUMER_VERDICT`` is the mapping we test against and
recommend, not something this package enforces.

Changing ``SCHEMA_VERSION``, a check code or a severity is a contract
change: see CHANGELOG.md ("Contract changes") and ``contract_fingerprint``.
"""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

from .audit_pyramid import INFO_CODES, SEVERITY, audit_one
from .chunkscan import SCAN_SEVERITY

__all__ = [
    "SCHEMA_VERSION", "SEVERITY_ORDER", "INTEGRITY_STATES",
    "GATE_SEVERITY", "RECOMMENDED_CONSUMER_VERDICT",
    "build_report", "audit_root", "integrity_of", "consumer_verdict",
    "load_schema", "validate_report", "contract", "contract_fingerprint",
]

SCHEMA_VERSION = "1.2.0"
TOOL = "zarr-pyramid-audit"

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}
INTEGRITY_STATES = ("PASS", "WARN", "UNKNOWN", "FAIL")

# A root with nothing to audit can never be PASS, whatever its severity.
NOTHING_TO_AUDIT = frozenset({"ROOT_ABSENT", "EMPTY_ZARR_DIR", "TIFXYZ_ABSENT"})

# Codes that only the gate / CLI wrappers emit (not audit_one).
GATE_SEVERITY = {"GATE_UNREADABLE": "high", "GATE_ROOT_ABSENT": "high",
                 "AUDIT_ERROR": "high"}

# What we recommend a consumer does with each integrity state. ScrolIQ owns
# its own policy (scrollq/health.py); tests/test_contract.py pins this table
# so a change here is deliberate. "DEFER_TO_QUALITY" means integrity has no
# objection and the consumer's own scoring decides.
RECOMMENDED_CONSUMER_VERDICT = {
    "FAIL": "DO NOT TRAIN",
    "UNKNOWN": "DO NOT TRAIN",     # fail closed, like `zpa-gate`
    "WARN": "CAUTION",
    "PASS": "DEFER_TO_QUALITY",
}


def _tool_version() -> str:
    try:
        from importlib.metadata import version
        return version(TOOL)
    except Exception:  # running from a checkout without install
        return "unknown"


def _finding_evidence(f: dict, pm, levels_by_path: dict) -> str:
    """The evidence state a single finding rests on."""
    code = f["code"]
    if code == "ACCESS_UNKNOWN":
        return "UNKNOWN"
    if code == "METADATA_UNREADABLE":
        return "PRESENT"
    lv = levels_by_path.get(f.get("level") or "")
    if code == "LEVEL_NO_CHUNKS" and lv is not None:
        return lv.chunk_evidence_state
    if code == "LEVEL_MISSING" and lv is not None:
        return lv.evidence_state
    if code in ("ROOT_ABSENT", "EMPTY_ZARR_DIR"):
        return pm.evidence_state
    return "PRESENT"


def integrity_of(findings: list[dict]) -> str:
    """Summarise findings into PASS / WARN / UNKNOWN / FAIL.

    A confirmed ``high`` defect outranks missing evidence (the volume is
    known-bad regardless); missing evidence -- or a root with nothing to
    audit -- outranks ``medium`` (a clean verdict cannot be issued).
    Otherwise ``low`` and ``info`` do not block.
    """
    sev = {f["severity"] for f in findings}
    if "high" in sev:
        return "FAIL"
    if any(f["code"] in ("ACCESS_UNKNOWN", "GATE_UNREADABLE")
           or f["code"] in NOTHING_TO_AUDIT
           or f.get("evidence_state") == "UNKNOWN" for f in findings):
        return "UNKNOWN"
    if "medium" in sev:
        return "WARN"
    return "PASS"


def consumer_verdict(report: dict) -> str:
    """The recommended consumer action for a report (see module docstring)."""
    return RECOMMENDED_CONSUMER_VERDICT[report["integrity"]]


def _max_severity(findings: list[dict]) -> str:
    if not findings:
        return "none"
    return max((f["severity"] for f in findings), key=SEVERITY_ORDER.__getitem__)


def build_report(pm, *, findings=None, pyramid_record=None) -> dict:
    """Build the schema-versioned report for one ``PyramidMeta``.

    Pass ``findings``/``pyramid_record`` if ``audit_one(pm)`` already ran.
    """
    if findings is None or pyramid_record is None:
        findings, _, pyramid_record = audit_one(pm)
    levels_by_path = {lv.path: lv for lv in pm.levels}

    out_findings = []
    for f in findings:
        out_findings.append({
            "code": f["code"],
            "severity": f["severity"],
            "level": f["level"],
            "detail": f["detail"],
            "observed": f.get("observed", ""),
            "expected": f.get("expected", ""),
            "evidence_state": _finding_evidence(f, pm, levels_by_path),
            "actionable": f["code"] not in INFO_CODES,
        })

    levels = []
    chunk_states = {"PRESENT": 0, "ABSENT": 0, "UNKNOWN": 0}
    for lv in pm.levels:
        levels.append({
            "path": lv.path,
            "index": lv.index,
            "present": bool(lv.present),
            "evidence_state": lv.evidence_state,
            "evidence_reason": lv.evidence_reason,
            "shape": lv.shape,
            "chunks": lv.chunks,
            "dtype": lv.dtype,
            "declared_scale": lv.declared_scale,
            "zarr_format": lv.zarr_format,
            "has_chunks": lv.has_chunks,
            "chunk_evidence_state": lv.chunk_evidence_state,
            "chunk_evidence_reason": lv.chunk_evidence_reason,
        })
        if lv.present:
            chunk_states[lv.chunk_evidence_state] = (
                chunk_states.get(lv.chunk_evidence_state, 0) + 1)

    kind = pyramid_record.get("kind") or (
        "pyramid" if pm.has_multiscales else pm.node_kind)
    integrity = integrity_of(out_findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "tool_version": _tool_version(),
        "root": pm.root,
        "kind": kind,
        "zarr_format": pm.zarr_format,
        "evidence": {"state": pm.evidence_state, "reason": pm.evidence_reason},
        "integrity": integrity,
        "max_severity": _max_severity(out_findings),
        "coverage": {
            "levels_declared": len(pm.levels),
            "levels_present": sum(1 for lv in pm.levels if lv.present),
            "levels_unknown": sum(1 for lv in pm.levels
                                  if lv.evidence_state == "UNKNOWN"),
            "chunk_presence": chunk_states,
        },
        "levels": levels,
        "findings": out_findings,
    }


def audit_root(store, root: str, **read_kw) -> dict:
    """Read one root from ``store`` and return its report.

    Never raises for transport failures: those surface as UNKNOWN evidence.
    An unexpected exception becomes a ``high`` AUDIT_ERROR finding, so a
    crash can never read as a clean result.
    """
    from .zarrmeta import read_pyramid
    try:
        pm = read_pyramid(store, root, **read_kw)
        return build_report(pm)
    except Exception as exc:  # noqa: BLE001 -- report, never crash clean
        finding = {
            "code": "AUDIT_ERROR", "severity": "high", "level": "",
            "detail": f"{type(exc).__name__}: {exc}", "observed": "",
            "expected": "", "evidence_state": "UNKNOWN", "actionable": True,
        }
        return {
            "schema_version": SCHEMA_VERSION, "tool": TOOL,
            "tool_version": _tool_version(), "root": root.rstrip("/"),
            "kind": "audit_error", "zarr_format": None,
            "evidence": {"state": "UNKNOWN", "reason": "AUDIT_ERROR"},
            "integrity": "FAIL", "max_severity": "high",
            "coverage": {"levels_declared": 0, "levels_present": 0,
                         "levels_unknown": 0,
                         "chunk_presence": {"PRESENT": 0, "ABSENT": 0,
                                            "UNKNOWN": 0}},
            "levels": [], "findings": [finding],
        }


# ---- schema + contract ----------------------------------------------------

SCHEMA_FILES = {"pyramid": "audit-report.schema.json",
                "tifxyz": "tifxyz-report.schema.json"}


def load_schema(kind: str = "pyramid") -> dict:
    """The JSON Schema (draft 2020-12) for one report kind.

    ``"pyramid"`` covers every Zarr root report (``build_report`` /
    ``audit_root``); ``"tifxyz"`` covers ``zpa.tifxyz.audit_surface``.
    """
    text = files("zpa").joinpath("data", SCHEMA_FILES[kind]).read_text(
        encoding="utf-8")
    return json.loads(text)


def schema_kind(report: dict) -> str:
    return "tifxyz" if report.get("kind") == "tifxyz" else "pyramid"


def validate_report(report: dict, kind: str | None = None) -> list[str]:
    """Dependency-free structural validation against the bundled schema.

    Covers what the schema uses: type, required, enum, const, properties,
    additionalProperties=false, items, $ref into $defs. Returns a list of
    error strings (empty = valid). Use ``jsonschema`` for full validation.
    """
    schema = load_schema(kind or schema_kind(report))
    errors: list[str] = []
    types = {"object": dict, "array": list, "string": str, "boolean": bool,
             "null": type(None)}

    def resolve(node):
        while "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            node = schema["$defs"][name]
        return node

    def type_ok(value, t):
        if t == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if t == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        return isinstance(value, types[t])

    def check(value, node, where):
        node = resolve(node)
        t = node.get("type")
        if t is not None:
            allowed = t if isinstance(t, list) else [t]
            if not any(type_ok(value, a) for a in allowed):
                errors.append(f"{where}: expected {t}, got {type(value).__name__}")
                return
        if "const" in node and value != node["const"]:
            errors.append(f"{where}: expected {node['const']!r}, got {value!r}")
        if "enum" in node and value not in node["enum"]:
            errors.append(f"{where}: {value!r} not in {node['enum']}")
        if isinstance(value, dict):
            props = node.get("properties", {})
            for key in node.get("required", []):
                if key not in value:
                    errors.append(f"{where}: missing required {key!r}")
            for key, sub in value.items():
                if key in props:
                    check(sub, props[key], f"{where}.{key}")
                elif node.get("additionalProperties") is False:
                    errors.append(f"{where}: unexpected property {key!r}")
                elif isinstance(node.get("additionalProperties"), dict):
                    check(sub, node["additionalProperties"], f"{where}.{key}")
        if isinstance(value, list) and "items" in node:
            for i, item in enumerate(value):
                check(item, node["items"], f"{where}[{i}]")

    check(report, schema, "$")
    return errors


def _tifxyz_severity() -> dict:
    from .tifxyz import TIFXYZ_SEVERITY  # lazy: zpa.tifxyz imports this module
    return TIFXYZ_SEVERITY


def contract() -> dict:
    """Everything a downstream consumer may branch on, as one document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "audit_codes": dict(sorted(SEVERITY.items())),
        "gate_codes": dict(sorted(GATE_SEVERITY.items())),
        "chunk_scan_codes": dict(sorted(SCAN_SEVERITY.items())),
        "tifxyz_codes": dict(sorted(_tifxyz_severity().items())),
        "info_codes": sorted(INFO_CODES),
        "nothing_to_audit_codes": sorted(NOTHING_TO_AUDIT),
        "integrity_states": list(INTEGRITY_STATES),
        "recommended_consumer_verdict": dict(RECOMMENDED_CONSUMER_VERDICT),
    }


def contract_fingerprint() -> str:
    """Short stable hash of ``contract()``.

    CHANGELOG.md must mention the current fingerprint; a check-code,
    severity, schema-version or verdict-mapping change alters it and fails
    tests/test_contract.py until a migration note is written.
    """
    blob = json.dumps(contract(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:12]
