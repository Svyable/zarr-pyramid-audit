#!/usr/bin/env bash
# Local preflight: audit Zarr roots before you upload, train or publish.
#
#   examples/preflight.sh <base> <root> [<root> ...]
#
#   <base>  a local staging directory, file://..., https://... or s3://...
#   <root>  path of a Zarr root relative to <base>
#
# Writes zpa-preflight.json (schema_version 1.2.0; one full audit report per
# root, see src/zpa/data/audit-report.schema.json) and exits non-zero when any
# root has a high-severity finding, unreadable evidence, or does not exist.
#
# Try it offline on the committed fixture corpus:
#   examples/preflight.sh fixtures/zarr clean_v2.zarr                 # exit 0
#   examples/preflight.sh fixtures/zarr clean_v2.zarr missing_level.zarr  # exit 1
set -euo pipefail

if [ "$#" -lt 2 ]; then
  sed -n '2,15p' "$0" >&2
  exit 2
fi

base="$1"; shift
args=()
for root in "$@"; do args+=(--root "$root"); done

status=0
zpa-gate --base "$base" "${args[@]}" --fail-on "${ZPA_FAIL_ON:-high}" \
  --out "${ZPA_OUT:-zpa-preflight.json}" || status=$?

case "$status" in
  0) echo "preflight: PASS -> ${ZPA_OUT:-zpa-preflight.json}" ;;
  1) echo "preflight: FAIL (see ${ZPA_OUT:-zpa-preflight.json})" >&2 ;;
  *) echo "preflight: usage error ($status)" >&2 ;;
esac
exit "$status"
