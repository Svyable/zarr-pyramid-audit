# Exact-volume TIFXYZ upper-bound control

This create-only live control uses the same PHerc0139 surface called out in the
2026-10-01 corpus survey:

`PHerc0139/segments/20250108000001-w026_2025010854/mesh/20250108000001-on-20250820105138-2.403um.tifxyz`

The surface declares target volume `20250820105138`. Its exact level-0 shape
is frozen here as **[z,y,x] = [19393, 26105, 26105]**.

The Oct. 1 content audit already showed that this surface extends below zero and
also above the z end of that scan. Contract 1.4.0 adds the missing upper-bound
check. This workflow must therefore observe both:

- `TIFXYZ_NEGATIVE_COORDINATE`; and
- `TIFXYZ_TARGET_VOLUME_OVERRUN`.

The command binds the exact declared target ID before accepting the target
shape, so this is a volume-specific control rather than a filename heuristic.

The measured report is committed once by the workflow. It is evidence that the
new check works on a real public surface; it is **not** the still-pending
shape-resolved rerun of all 1,539 public surfaces.
