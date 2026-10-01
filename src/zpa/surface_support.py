"""Surface-prediction support audit against its source masked CT.

This is an evidence tool, not a defect classifier. It measures how much
surface-prediction foreground lies where the aligned masked CT is non-zero.
It is useful for detecting prediction halo / phantom support without turning
that measurement into a hidden quality score.

The voxel-support method was independently reimplemented for ZPA after
reviewing the MIT-licensed public implementation in
axiosdevs/herculaneum-scroll-tools/ct_support/audit_ct_support.py
(file SHA 3e8dbbc35aabca7a0d32af890436d05ba386bd59, inspected 2026-09-30).

Outputs use ZPA's normal RunManifest and no-silent-overwrite semantics.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import fsspec
import numpy as np
import zarr

from .runio import RunManifest, write_json


DEFAULT_STRIPE_BYTES = 512_000_000


def validate_expected_volume_id(
    predictions_path: str, ct_path: str, expected_volume_id: str | None
) -> None:
    """Fail closed if either input path is not tied to the expected volume."""
    if not expected_volume_id:
        return
    missing = [
        label
        for label, path in (("predictions", predictions_path), ("ct", ct_path))
        if expected_volume_id not in path
    ]
    if missing:
        raise ValueError(
            f"expected volume ID {expected_volume_id!r} is missing from "
            + " and ".join(missing)
            + " path"
        )


def open_array(path: str, *, anon: bool = False):
    """Open a local, HTTP(S), S3, GCS, or compatible Zarr array read-only."""
    if "://" not in path:
        return zarr.open_array(path, mode="r")

    protocol, rest = path.split("://", 1)
    options: dict[str, Any] = {}
    if protocol in {"s3", "gs", "gcs"} and anon:
        options["anon"] = True

    from zarr.storage import FsspecStore

    fs = fsspec.filesystem(protocol, asynchronous=True, **options)
    return zarr.open_array(FsspecStore(fs, path=rest.rstrip("/")), mode="r")


def count_block(
    prediction: np.ndarray, ct: np.ndarray, threshold: int = 127
) -> tuple[np.ndarray, np.ndarray]:
    """Per-z counts of prediction positives and unsupported positives."""
    p = np.asarray(prediction) > threshold
    c = np.asarray(ct) > 0
    if p.shape != c.shape:
        raise ValueError(f"block shape mismatch: predictions {p.shape} vs CT {c.shape}")
    if p.ndim != 3:
        raise ValueError(f"expected 3D blocks, got {p.ndim}D")
    positives = p.sum(axis=(1, 2), dtype=np.int64)
    phantom = (p & ~c).sum(axis=(1, 2), dtype=np.int64)
    return positives, phantom


def audit_arrays(
    predictions,
    ct,
    *,
    threshold: int = 127,
    slab_stride: int = 12,
    stripe_bytes: int = DEFAULT_STRIPE_BYTES,
    progress: bool = False,
) -> dict:
    """Measure support on deterministic chunk-aligned z slabs.

    slab_stride=1 visits every prediction z chunk. Larger values sample every
    Nth z chunk while measuring every plane inside each selected chunk.
    Failed or skipped slabs are never silently dropped: array reads raise and
    the run manifest records the error.
    """
    pshape = tuple(int(v) for v in predictions.shape)
    cshape = tuple(int(v) for v in ct.shape)
    if pshape != cshape:
        raise ValueError(
            f"grid mismatch: predictions {pshape} vs CT {cshape}; "
            "use arrays on the same voxel grid"
        )
    if len(pshape) != 3:
        raise ValueError(f"expected a 3D volume, got shape {pshape}")
    if slab_stride < 1:
        raise ValueError("slab_stride must be >= 1")
    if stripe_bytes < 1:
        raise ValueError("stripe_bytes must be >= 1")

    pchunks = tuple(int(v) for v in predictions.chunks)
    cchunks = tuple(int(v) for v in ct.chunks)
    if len(pchunks) != 3 or len(cchunks) != 3:
        raise ValueError("prediction and CT chunk shapes must be 3D")

    z_size, y_size, x_size = pshape
    pcz, pcy, _ = pchunks
    step = slab_stride * pcz
    slab_starts = list(range(0, z_size, step))

    # Two temporary boolean arrays are materialized by count_block. Keep the
    # Y stripe aligned to prediction chunks while honoring the memory budget.
    bytes_per_y = max(1, 2 * pcz * x_size)
    stripe_y = max(pcy, (stripe_bytes // bytes_per_y // pcy) * pcy)
    stripe_y = max(pcy, stripe_y)

    total_pos = 0
    total_phantom = 0
    rows: list[dict] = []
    t0 = time.time()

    for slab_i, z0 in enumerate(slab_starts):
        z1 = min(z0 + pcz, z_size)
        pos_z = np.zeros(z1 - z0, dtype=np.int64)
        phantom_z = np.zeros(z1 - z0, dtype=np.int64)

        for y0 in range(0, y_size, stripe_y):
            y1 = min(y0 + stripe_y, y_size)
            pos, phantom = count_block(
                predictions[z0:z1, y0:y1, :],
                ct[z0:z1, y0:y1, :],
                threshold=threshold,
            )
            pos_z += pos
            phantom_z += phantom

        for k in range(z1 - z0):
            pos = int(pos_z[k])
            phantom = int(phantom_z[k])
            rows.append(
                {
                    "z": z0 + k,
                    "positives": pos,
                    "phantom": phantom,
                    "phantom_frac": (phantom / pos) if pos else None,
                }
            )
        total_pos += int(pos_z.sum())
        total_phantom += int(phantom_z.sum())

        if progress:
            frac = total_phantom / total_pos if total_pos else 0.0
            print(
                f"[{slab_i + 1}/{len(slab_starts)}] z={z0}:{z1} "
                f"cumulative phantom={frac:.4f}",
                flush=True,
            )

    phantom_frac = total_phantom / total_pos if total_pos else None
    support_frac = (1.0 - phantom_frac) if phantom_frac is not None else None
    return {
        "mode": "sampled_voxel_support",
        "shape": list(pshape),
        "prediction_chunks": list(pchunks),
        "ct_chunks": list(cchunks),
        "threshold": int(threshold),
        "slab_stride": int(slab_stride),
        "planned_slabs": len(slab_starts),
        "slabs_measured": len(slab_starts),
        "planes_measured": len(rows),
        "plane_coverage_frac": (len(rows) / z_size) if z_size else 0.0,
        "sampled_positives": total_pos,
        "sampled_phantom": total_phantom,
        "sampled_phantom_frac": phantom_frac,
        "sampled_support_frac": support_frac,
        "elapsed_seconds": round(time.time() - t0, 3),
        "per_plane": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Measure surface-prediction foreground support against an aligned "
            "masked CT volume. Reports evidence; does not classify a defect."
        )
    )
    ap.add_argument("--predictions", required=True, help="surface-prediction Zarr array")
    ap.add_argument("--ct", required=True, help="masked CT Zarr array on the same grid")
    ap.add_argument(
        "--expected-volume-id",
        help=(
            "optional compliance guard: refuse the run unless this exact volume "
            "ID appears in both prediction and CT paths"
        ),
    )
    ap.add_argument("--threshold", type=int, default=127)
    ap.add_argument("--slab-stride", type=int, default=12)
    ap.add_argument("--stripe-bytes", type=int, default=DEFAULT_STRIPE_BYTES)
    ap.add_argument("--anon", action="store_true", help="anonymous object-store access")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--quiet", action="store_true")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)

    validate_expected_volume_id(
        args.predictions, args.ct, args.expected_volume_id
    )

    with RunManifest("surface_support", out_dir, argv=argv) as manifest:
        manifest.set(
            "inputs",
            {
                "predictions": args.predictions,
                "ct": args.ct,
                "expected_volume_id": args.expected_volume_id,
                "threshold": args.threshold,
                "slab_stride": args.slab_stride,
                "stripe_bytes": args.stripe_bytes,
                "anon": args.anon,
            },
        )
        predictions = open_array(args.predictions, anon=args.anon)
        ct = open_array(args.ct, anon=args.anon)
        report = audit_arrays(
            predictions,
            ct,
            threshold=args.threshold,
            slab_stride=args.slab_stride,
            stripe_bytes=args.stripe_bytes,
            progress=not args.quiet,
        )
        report["predictions"] = args.predictions
        report["ct"] = args.ct

        out = write_json(out_dir / "surface_support.json", report)
        manifest.add_output(out, "surface-prediction / CT support evidence")
        manifest.count("slabs_measured", report["slabs_measured"])
        manifest.count("planes_measured", report["planes_measured"])
        manifest.set("sampled_support_frac", report["sampled_support_frac"])
        manifest.set("sampled_phantom_frac", report["sampled_phantom_frac"])

        if report["sampled_support_frac"] is None:
            support_text = "n/a (no prediction positives sampled)"
        else:
            support_text = f"{report['sampled_support_frac']:.4f}"
        phantom_text = (
            "n/a"
            if report["sampled_phantom_frac"] is None
            else f"{report['sampled_phantom_frac']:.4f}"
        )
        print(
            f"planes measured: {report['planes_measured']:,} | "
            f"coverage {report['plane_coverage_frac']:.4f} | "
            f"positives {report['sampled_positives']:,} | "
            f"phantom {report['sampled_phantom']:,} ({phantom_text}) | "
            f"support {support_text}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
