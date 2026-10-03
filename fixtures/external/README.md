# External fixture references

This directory records third-party cases used or considered for independent
validation. A pin is not the same thing as permission to redistribute or use a
case in prize evidence.

## Oztest

`oztest-pin.json` fixes the source repository, commit, individual blob SHAs
and upstream valid/invalid classification for a small OME-Zarr 0.5 image
reference set. Expected status comes from Oztest's directory classification,
not from filenames or ZPA output. That distinction matters: for example,
`invalid_axis_units.json` is under Oztest's **valid** directory at the pinned
commit.

No Oztest case contents are copied into this repository. At the pinned commit
the Oztest repository root has no `LICENSE` file and its `pyproject.toml`
does not declare a license, while its README labels the project alpha and warns
that cases may need correction. Until reuse terms are verified, the pin is
reference-only and must not be counted as Scroll Prize validation evidence.

The pinned v0.5 cases are `parse_attributes` cases, not full Zarr stores. If
they become usable, any adapter that wraps those attributes in a hierarchy must
be documented and tested separately so adapter choices cannot be mistaken for
upstream ground truth.
