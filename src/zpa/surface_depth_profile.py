"""Deterministic depth-profile evidence for rendered surface-volume Zarr arrays.

Ink models are sensitive to which slices around the papyrus surface are
rendered. A surface volume can be structurally valid Zarr yet still be a poor
model input because the wrong depth window was rendered, slices are duplicated,
or sampled layers are empty. This tool measures those conditions without
classifying ink or readability.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .runio import RunManifest, write_json
from .surface_support import open_array


def _tile_starts(size: int, tile: int, grid: int) -> list[int]:
    if size <= 0:
        return []
    tile = min(tile, size)
    if grid <= 1 or size == tile:
        return [max(0, (size - tile) // 2)]
    max_start = size - tile
    starts = np.linspace(0, max_start, num=grid)
    return sorted({int(round(v)) for v in starts})


def _tile_metrics(tile: np.ndarray) -> dict[str, float | int]:
    x = np.asarray(tile)
    if x.ndim != 2:
        raise ValueError(f"expected 2D tile, got {x.ndim}D")
    finite = np.isfinite(x)
    finite_count = int(finite.sum())
    total = int(x.size)
    if finite_count == 0:
        return {
            "pixels": total,
            "finite_pixels": 0,
            "nonzero_pixels": 0,
            "sum": 0.0,
            "sum_sq": 0.0,
            "grad_sum": 0.0,
            "grad_count": 0,
            "p01": 0.0,
            "p50": 0.0,
            "p99": 0.0,
        }

    vals = x[finite].astype(np.float64, copy=False)
    nonzero = int(np.count_nonzero(vals))
    sum_v = float(vals.sum(dtype=np.float64))
    sum_sq = float(np.square(vals, dtype=np.float64).sum(dtype=np.float64))

    xf = x.astype(np.float64, copy=False)
    gx = np.abs(np.diff(xf, axis=1))
    gy = np.abs(np.diff(xf, axis=0))
    gx_f = gx[np.isfinite(gx)]
    gy_f = gy[np.isfinite(gy)]
    grad_sum = float(gx_f.sum(dtype=np.float64) + gy_f.sum(dtype=np.float64))
    grad_count = int(gx_f.size + gy_f.size)

    p01, p50, p99 = np.percentile(vals, [1, 50, 99])
    return {
        "pixels": total,
        "finite_pixels": finite_count,
        "nonzero_pixels": nonzero,
        "sum": sum_v,
        "sum_sq": sum_sq,
        "grad_sum": grad_sum,
        "grad_count": grad_count,
        "p01": float(p01),
        "p50": float(p50),
        "p99": float(p99),
    }


def profile_surface_volume(
    array,
    *,
    grid: int = 3,
    tile_size: int = 128,
    depth_stride: int = 1,
    expected_depth: int | None = None,
) -> dict[str, Any]:
    """Profile deterministic XY tiles across the depth axis of a 3D array."""
    shape = tuple(int(v) for v in array.shape)
    if len(shape) != 3:
        raise ValueError(f"expected [depth,y,x] 3D surface volume, got {shape}")
    if grid < 1:
        raise ValueError("grid must be >= 1")
    if tile_size < 1:
        raise ValueError("tile_size must be >= 1")
    if depth_stride < 1:
        raise ValueError("depth_stride must be >= 1")

    depth, height, width = shape
    ys = _tile_starts(height, tile_size, grid)
    xs = _tile_starts(width, tile_size, grid)
    tile_h = min(tile_size, height)
    tile_w = min(tile_size, width)
    depth_indices = list(range(0, depth, depth_stride))

    rows: list[dict[str, Any]] = []
    digest_groups: dict[str, list[int]] = {}

    for z in depth_indices:
        totals = {
            "pixels": 0,
            "finite_pixels": 0,
            "nonzero_pixels": 0,
            "sum": 0.0,
            "sum_sq": 0.0,
            "grad_sum": 0.0,
            "grad_count": 0,
        }
        p01s: list[float] = []
        p50s: list[float] = []
        p99s: list[float] = []
        h = hashlib.sha256()

        for y0 in ys:
            for x0 in xs:
                tile = np.asarray(array[z, y0 : y0 + tile_h, x0 : x0 + tile_w])
                metrics = _tile_metrics(tile)
                for key in totals:
                    totals[key] += metrics[key]
                p01s.append(float(metrics["p01"]))
                p50s.append(float(metrics["p50"]))
                p99s.append(float(metrics["p99"]))
                h.update(np.asarray(tile, dtype="<f4").tobytes(order="C"))

        finite_n = int(totals["finite_pixels"])
        mean = float(totals["sum"]) / finite_n if finite_n else None
        variance = None
        std = None
        if finite_n:
            variance = max(
                0.0,
                float(totals["sum_sq"]) / finite_n - float(mean) ** 2,
            )
            std = variance**0.5
        grad_energy = (
            float(totals["grad_sum"]) / int(totals["grad_count"])
            if totals["grad_count"]
            else None
        )
        p01 = float(np.mean(p01s)) if p01s else None
        p50 = float(np.mean(p50s)) if p50s else None
        p99 = float(np.mean(p99s)) if p99s else None
        dynamic = (p99 - p01) if p01 is not None and p99 is not None else None
        digest = h.hexdigest()
        digest_groups.setdefault(digest, []).append(z)

        rows.append(
            {
                "depth_index": z,
                "sampled_tiles": len(ys) * len(xs),
                "sampled_pixels": int(totals["pixels"]),
                "finite_frac": (
                    float(totals["finite_pixels"]) / int(totals["pixels"])
                    if totals["pixels"]
                    else None
                ),
                "nonzero_frac": (
                    float(totals["nonzero_pixels"]) / finite_n
                    if finite_n
                    else None
                ),
                "mean": mean,
                "std": std,
                "p01": p01,
                "p50": p50,
                "p99": p99,
                "dynamic_range_p99_p01": dynamic,
                "gradient_energy": grad_energy,
                "sample_all_zero": bool(
                    finite_n and int(totals["nonzero_pixels"]) == 0
                ),
                "sample_digest_sha256": digest,
            }
        )

    duplicate_groups = [
        indices for indices in digest_groups.values() if len(indices) > 1
    ]
    gradient_rows = [
        row for row in rows if row["gradient_energy"] is not None
    ]
    dynamic_rows = [
        row for row in rows if row["dynamic_range_p99_p01"] is not None
    ]
    peak_gradient = (
        max(gradient_rows, key=lambda r: r["gradient_energy"])["depth_index"]
        if gradient_rows
        else None
    )
    peak_dynamic = (
        max(dynamic_rows, key=lambda r: r["dynamic_range_p99_p01"])["depth_index"]
        if dynamic_rows
        else None
    )
    center = (depth - 1) / 2.0 if depth else None

    expected_depth_ok = (
        None if expected_depth is None else depth == int(expected_depth)
    )

    chunks = getattr(array, "chunks", None)
    return {
        "mode": "surface_depth_profile",
        "shape": list(shape),
        "chunks": list(chunks) if chunks is not None else None,
        "sampling": {
            "grid": int(grid),
            "tile_size": int(tile_size),
            "depth_stride": int(depth_stride),
            "depth_indices": depth_indices,
            "y_starts": ys,
            "x_starts": xs,
        },
        "expected_depth": expected_depth,
        "expected_depth_ok": expected_depth_ok,
        "center_depth_index": center,
        "peak_gradient_depth_index": peak_gradient,
        "peak_gradient_offset_from_center": (
            float(peak_gradient - center)
            if peak_gradient is not None and center is not None
            else None
        ),
        "peak_dynamic_range_depth_index": peak_dynamic,
        "all_zero_sampled_depths": [
            row["depth_index"] for row in rows if row["sample_all_zero"]
        ],
        "duplicate_sample_digest_depth_groups": duplicate_groups,
        "per_depth": rows,
    }


def validate_volume_lineage(
    source_volume_id: str | None, expected_volume_id: str | None
) -> None:
    if expected_volume_id is None:
        return
    if source_volume_id != expected_volume_id:
        raise ValueError(
            "source volume does not match expected eligible volume: "
            f"{source_volume_id!r} != {expected_volume_id!r}"
        )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Profile a rendered [depth,y,x] surface-volume Zarr across depth "
            "using deterministic XY tiles."
        )
    )
    ap.add_argument("--surface-volume", required=True)
    ap.add_argument("--anon", action="store_true")
    ap.add_argument("--grid", type=int, default=3)
    ap.add_argument("--tile-size", type=int, default=128)
    ap.add_argument("--depth-stride", type=int, default=1)
    ap.add_argument(
        "--expected-depth",
        type=int,
        help="optional fail-closed check for the recipe's expected slice count",
    )
    ap.add_argument(
        "--source-volume-id",
        help="exact CT volume id used to generate this rendered surface volume",
    )
    ap.add_argument(
        "--expected-volume-id",
        help="optional prize/compliance guard matched exactly to --source-volume-id",
    )
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    validate_volume_lineage(args.source_volume_id, args.expected_volume_id)

    with RunManifest("surface_depth_profile", out_dir, argv=argv) as manifest:
        manifest.set(
            "inputs",
            {
                "surface_volume": args.surface_volume,
                "source_volume_id": args.source_volume_id,
                "expected_volume_id": args.expected_volume_id,
                "grid": args.grid,
                "tile_size": args.tile_size,
                "depth_stride": args.depth_stride,
                "expected_depth": args.expected_depth,
                "anon": args.anon,
            },
        )
        array = open_array(args.surface_volume, anon=args.anon)
        report = profile_surface_volume(
            array,
            grid=args.grid,
            tile_size=args.tile_size,
            depth_stride=args.depth_stride,
            expected_depth=args.expected_depth,
        )
        report["surface_volume"] = args.surface_volume
        report["source_volume_id"] = args.source_volume_id
        report["expected_volume_id"] = args.expected_volume_id

        out = write_json(out_dir / "surface_depth_profile.json", report)
        manifest.add_output(out, "rendered surface-volume depth-profile evidence")
        manifest.count("depths_profiled", len(report["per_depth"]))
        manifest.count(
            "all_zero_sampled_depths",
            len(report["all_zero_sampled_depths"]),
        )
        manifest.count(
            "duplicate_sample_digest_groups",
            len(report["duplicate_sample_digest_depth_groups"]),
        )

        ok = report["expected_depth_ok"] is not False
        if args.format == "json":
            import json

            print(json.dumps(report, indent=2))
        elif args.format == "github":
            if report["expected_depth_ok"] is False:
                print(
                    "::error title=SURFACE_DEPTH_MISMATCH::"
                    f"expected {args.expected_depth} slices, got {report['shape'][0]}"
                )
            else:
                print(
                    "::notice title=SURFACE_DEPTH_PROFILE::"
                    f"depth={report['shape'][0]} "
                    f"peak_gradient={report['peak_gradient_depth_index']} "
                    f"zero_depths={len(report['all_zero_sampled_depths'])} "
                    f"duplicate_groups={len(report['duplicate_sample_digest_depth_groups'])}"
                )
        else:
            print(
                f"depth={report['shape'][0]} | "
                f"peak gradient={report['peak_gradient_depth_index']} | "
                f"all-zero sampled depths={report['all_zero_sampled_depths']} | "
                "duplicate sampled-depth groups="
                f"{report['duplicate_sample_digest_depth_groups']}"
            )
            if report["expected_depth_ok"] is False:
                print(
                    f"expected depth {args.expected_depth}, got {report['shape'][0]}"
                )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
