# Third-party notices

This repository is MIT licensed. Third-party software, data, standards, and
vendored components remain under their own licenses and terms.

This file records the material upstream projects used directly by
`zarr-pyramid-audit`. The dependency versions actually installed for a run
remain part of that run's environment/provenance record.

## Fork lineage

### sgsllc-jr/zarr-pyramid-audit

Source: https://github.com/sgsllc-jr/zarr-pyramid-audit

License: MIT

The Svyable repository is a fork and retains upstream attribution. The
upstream project established the original read-only, header-first OME-Zarr
auditing approach and early `dl.ash2txt.org` campaign.

## Vendored binary

### superoptimizer/volume-compressor

Source: https://github.com/superoptimizer/volume-compressor

Pinned source commit:
`3e549a345fde0a668a37bf248137e78317e3489f`

License: MIT

A Linux x86-64 `libvolcomp` decoder is vendored for decoding Vesuvius
volcomp chunks. Exact build and verification details are recorded in
`src/zpa/data/VOLCOMP_PROVENANCE.md`.

## Runtime dependencies

- Requests — https://github.com/psf/requests — HTTP transport.
- NumPy — https://github.com/numpy/numpy — numerical array operations.
- Numcodecs — https://github.com/zarr-developers/numcodecs — codec support.
- Zarr Python — https://github.com/zarr-developers/zarr-python — Zarr support
  for chunk/surface paths.
- fsspec — https://github.com/fsspec/filesystem_spec — filesystem abstraction.
- s3fs — https://github.com/fsspec/s3fs — S3 access.

Optional TIFXYZ content decoding uses:

- tifffile — https://github.com/cgohlke/tifffile
- imagecodecs — https://github.com/cgohlke/imagecodecs

## Development and CI

- pytest — https://github.com/pytest-dev/pytest
- build — https://github.com/pypa/build
- setuptools — https://github.com/pypa/setuptools
- actions/checkout — https://github.com/actions/checkout
- actions/setup-python — https://github.com/actions/setup-python
- actions/upload-artifact — https://github.com/actions/upload-artifact

## Standards and data ecosystem

The project interoperates with OME-NGFF / OME-Zarr conventions and Vesuvius
Challenge / Scroll Prize public data and tooling. Their specifications, data,
models, and documentation are not relicensed by this repository.

For Vesuvius data citations and data-license terms, use the current official
data page: https://scrollprize.org/data

If a redistributed third-party component is added in the future, add its exact
source revision, license, and redistribution notice here in the same commit.
