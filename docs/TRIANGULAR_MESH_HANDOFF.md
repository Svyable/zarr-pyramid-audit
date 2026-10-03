# Triangular-mesh handoff contract

**October 2026 scope decision:** zarr-pyramid-audit (ZPA) will not duplicate
triangular-mesh diagnostics. Wavefront OBJ integrity, topology, winding and
flattening diagnostics belong to the downstream geometry layer in
[ScrolIQ](https://github.com/Svyable/scrollq).

This closes October goal G4 by choosing one owner instead of maintaining two
partially overlapping implementations.

## Why the boundary is here

ZPA owns input/storage integrity: Zarr structure, evidence semantics, chunk
presence/content, physical-scale claims, and native TIFXYZ surface-file
integrity. A triangular mesh introduces indexed-face, topology, winding and
parameterization semantics already evaluated downstream by ScrolIQ.

Duplicating that code here would create two severity systems and potentially two
answers for the same mesh.

## Owning command

```bash
scroliq-obj \
  --obj column_01.obj \
  --out column_01.obj-audit.json \
  --fail-on-findings
```

Implementation:
[`src/scrollq/obj_audit.py`](https://github.com/Svyable/scrollq/blob/main/src/scrollq/obj_audit.py)

The command is read-only. It checks parseability, finite/indexed geometry,
components, boundary loops/holes, non-manifold edges, winding consistency, edge
jumps, neighbouring-normal reversals, and UV-to-3D isometry when texture
coordinates exist.

## Shared report boundary

Preserve the ZPA input report and ScrolIQ mesh report as separate immutable
evidence artifacts. Do not translate a ScrolIQ geometry warning into a ZPA
finding code.

The parent campaign record should bind both reports without merging semantics:

```json
{
  "schema": "zpa-scroliq-mesh-handoff/1",
  "source_volume_id": "<exact eligible CT volume id>",
  "zpa_input_report": {
    "uri": "<repo-relative path or public URL>",
    "sha256": "<64 lowercase hex>"
  },
  "mesh_input": {
    "uri": "<OBJ path or URL>",
    "sha256": "<64 lowercase hex>"
  },
  "scroliq_obj_report": {
    "uri": "<repo-relative path or public URL>",
    "sha256": "<64 lowercase hex>",
    "diagnostic": "obj-mesh-audit",
    "schema_version": 1
  }
}
```

ZPA remains authoritative for storage/input integrity. ScrolIQ remains
authoritative for mesh geometry diagnostics.

## Grand Prize use

For each triangular-mesh intermediate, bind the exact eligible CT to its ZPA
report, hash the exact OBJ consumed, run `scroliq-obj`, and preserve both
report hashes beside flattening/render evidence. Missing or unreadable mesh
evidence stays missing; it is never treated as clean.

This handoff does **not** prove sheet identity, complete recto coverage, or
legible text. Those claims require downstream surface/coverage and ink evidence.
