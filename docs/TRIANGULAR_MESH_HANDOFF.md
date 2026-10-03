# Triangular-mesh handoff contract

**October 2026 scope decision:** zarr-pyramid-audit (ZPA) will not duplicate
triangular-mesh diagnostics. Wavefront OBJ integrity, topology, winding and
flattening diagnostics belong to the downstream geometry layer in
[ScrolIQ](https://github.com/Svyable/scrollq).

This closes October goal G4 by choosing one owner instead of maintaining two
partially overlapping implementations.

## Why the boundary is here

ZPA's responsibility is input/storage integrity: Zarr structure, evidence
semantics, chunk presence/content, physical-scale claims, and native TIFXYZ
surface-file integrity. Those checks answer whether an upstream artifact is
readable and internally consistent.

A triangular mesh introduces different semantics: indexed faces, manifoldness,
face winding, holes, neighbouring normals and UV-to-3D distortion. Those are
geometry/parameterization questions, and ScrolIQ already evaluates them in the
same pipeline that evaluates TIFXYZ geometry and Grand Prize surface evidence.

Duplicating that code here would create two severity systems and two potentially
divergent answers for the same mesh.

## Owning command

ScrolIQ owns the executable interface:

```bash
scroliq-obj \
  --obj column_01.obj \
  --out column_01.obj-audit.json \
  --fail-on-findings
```

Implementation:
[`src/scrollq/obj_audit.py`](https://github.com/Svyable/scrollq/blob/main/src/scrollq/obj_audit.py)

The command is read-only. A parse/error failure exits non-zero; with
`--fail-on-findings`, review findings also gate the pipeline.

## Shared report boundary

A Grand Prize pipeline should preserve the ZPA input report and the ScrolIQ mesh
report as separate immutable evidence artifacts. Do not translate a ScrolIQ
geometry warning into a ZPA finding code.

The ScrolIQ OBJ report currently exposes:

- `schema_version` and `diagnostic: "obj-mesh-audit"`;
- input provenance: OBJ SHA-256 and byte size;
- `status`: `pass`, `partial`, or `fail`;
- mesh counts and 3-D bounding box;
- topology: components, boundary edges/loops, holes, non-manifold edges and
  inconsistent winding;
- edge-length jump diagnostics;
- neighbouring-normal reversal diagnostics;
- UV-to-3D isometry diagnostics when texture coordinates exist;
- explicit `errors`, `warnings`, `findings`, and a claim limitation.

For cross-repo provenance, the parent campaign record should bind both reports
without merging their semantics:

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

The outer record is a provenance envelope only. ZPA remains authoritative for
storage/input integrity; ScrolIQ remains authoritative for the mesh diagnostics.

## Grand Prize use

For a submitted column or other triangular-mesh intermediate:

1. bind the exact eligible CT input to its ZPA report;
2. hash the OBJ that is actually consumed;
3. run `scroliq-obj` on that exact file;
4. preserve both report hashes beside the downstream flattening/render evidence;
5. treat an absent/unreadable mesh report as missing evidence rather than as a
   clean mesh.

This handoff does **not** prove that the mesh follows the papyrus sheet, that the
recto is complete, or that text is legible. Those claims require the downstream
surface/coverage and ink evidence in ScrolIQ and the final Grand Prize pipeline.
