#!/usr/bin/env python3
"""
discover_zarr.py -- find every Zarr group in a remote corpus, cheaply.

Breadth-first crawl of an HTTP autoindex (or S3 prefix), pruning hard so the
crawl never descends into a chunk tree or a patch-coordinate tree. A single
pyramid level can hold 400,000+ chunk directories; walking one would be both
useless and rude.

PRUNING RULES (each is counted in the manifest, so a run records exactly what
it chose not to look at):

  1. COORDINATE DIRS -- a name whose underscore-separated parts are ALL
     digits is a chunk or patch address, never a container worth crawling.
     Examples: "0", "3", "00000_02408_04560", "01024_02152_04304".
     Measured: this rule alone accounts for 7,013 of 7,105 directories in a
     Scroll1 crawl (98.7%), essentially all of them under
     volumetric-instance-labels/.

  2. SEGMENT DIRS -- timestamp-named directories that are DIRECT CHILDREN of
     a "paths" directory are segment folders (meshes, masks, layers, ppm).
     ~283 per scroll. Disable with --crawl-segments.

     This rule is deliberately scoped to `paths/` rather than applied to any
     timestamp-prefixed name. A global timestamp rule is UNSAFE: the root
       .../representations/predictions/fibers/
           20250801195441-Dataset004_sk-fibers_binary-20250728_v00
     is a genuine Zarr group carrying a real .zgroup and no .zarr suffix, and
     a global rule would silently discard it.

  3. SKIP_NAMES -- housekeeping directories with no scientific content.

A directory recognised as a Zarr root is recorded and NOT entered. The
zarr-name test runs BEFORE every prune test, so a Zarr root can never be
pruned by a naming heuristic.

Outputs (into --out-dir, existing files backed up, never overwritten):
    discover_zarr.roots.jsonl     one record per Zarr root found
    discover_zarr.dirs.jsonl      one record per directory listed
    discover_zarr.manifest.json   provenance for the run

Usage:
    python bin/discover_zarr.py --base https://dl.ash2txt.org/ \
        --prefix full-scrolls/ --max-depth 6
    python bin/discover_zarr.py --base https://dl.ash2txt.org/ --max-depth 9
"""

from __future__ import annotations

import argparse
import os
import posixpath
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zpa.httpstore import open_store           # noqa: E402
from zpa.pool import parallel_map              # noqa: E402
from zpa.runio import JsonlWriter, RunManifest  # noqa: E402

# Housekeeping directories that never hold survey-relevant data.
SKIP_NAMES = {
    ".git", ".github", "__pycache__", "working", "thaumato_outputs",
    "old_files", "logs", "node_modules", ".ipynb_checkpoints",
}

# Directory names whose children are segment folders (rule 2 scope).
SEGMENT_PARENTS = {"paths"}

# Rule 4: directory suffixes that denote a LEAF data format -- a directory that
# is itself a single artifact, holding only plain files. Entering one costs a
# request and can never yield a Zarr root.
#
#   .tifxyz  Volume Cartographer surface patch: meta.json + x.tif/y.tif/z.tif.
#            Measured: 89,237 of them under
#            datasets/spiral_datasets/PHercParis4/verified_patches/ alone.
#            At 25 rps that is ~60 minutes of requests yielding zero roots.
#
# Deliberately NOT listed here: ".ome.zarr.respool_g4" and similar. Names like
# "las_008_grad_mag.ome.zarr.respool_g4" are Zarr-derived but do not end in
# .zarr, so they must stay crawlable or their contents are lost.
LEAF_DIR_SUFFIXES = (".tifxyz",)


def is_leaf_format_dir(name: str) -> bool:
    n = name.lower().rstrip("/")
    return n.endswith(LEAF_DIR_SUFFIXES)


def looks_like_zarr_name(name: str) -> bool:
    """Conventional Zarr root naming. Checked BEFORE any prune rule."""
    n = name.lower().rstrip("/")
    return n.endswith(".zarr") or n.endswith(".ome.zarr")


def is_coordinate_dir_name(name: str) -> bool:
    """
    True for chunk indices and patch-coordinate directories.

    Covers plain numeric level/chunk names ("0", "3") and underscore-joined
    coordinate triplets ("00000_02408_04560"). Requires every underscore part
    to be non-empty and fully numeric, so "20230813_real_1" is NOT matched.
    """
    n = name.rstrip("/")
    if not n:
        return False
    parts = n.split("_")
    return all(p.isdigit() for p in parts)


def is_timestamp_prefixed(name: str) -> bool:
    """
    True when a name begins with an 8+ digit run (a date or datetime stamp).

    NEVER use this on its own to prune -- see rule 2 in the module docstring.
    It is only consulted for direct children of a SEGMENT_PARENTS directory.
    """
    n = name.rstrip("/")
    i = 0
    while i < len(n) and n[i].isdigit():
        i += 1
    return i >= 8


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="base URL (http(s):// or s3://)")
    ap.add_argument("--prefix", default="", help="path under base to start from")
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--max-rps", type=float, default=None,
                    help="global request rate cap (politeness); default unlimited")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--crawl-leaf-formats", action="store_true",
                    help="descend into leaf-format dirs such as *.tifxyz "
                         "(rule 4 off; adds ~89k requests on this corpus)")
    ap.add_argument("--crawl-segments", action="store_true",
                    help="descend into timestamp-named segment folders under "
                         "paths/ (rule 2 off; much slower)")
    ap.add_argument("--probe-unnamed", action="store_true",
                    help="also HEAD .zgroup in dirs not named *.zarr (slower, "
                         "finds roots that break the naming convention)")
    args = ap.parse_args()

    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp")
    os.makedirs(out_dir, exist_ok=True)

    store = open_store(args.base, timeout=args.timeout, max_rps=args.max_rps)

    roots_path = os.path.join(out_dir, "discover_zarr.roots.jsonl")
    dirs_path = os.path.join(out_dir, "discover_zarr.dirs.jsonl")

    seen: set[str] = set()
    seen_lock = threading.Lock()
    roots: list[dict] = []

    with RunManifest("discover_zarr", out_dir) as man, \
         JsonlWriter(roots_path) as w_roots, \
         JsonlWriter(dirs_path) as w_dirs:

        man.set("base", args.base)
        man.set("prefix", args.prefix)
        man.set("max_depth", args.max_depth)
        man.set("crawl_segments", bool(args.crawl_segments))
        man.set("skip_names", sorted(SKIP_NAMES))
        man.set("leaf_dir_suffixes", list(LEAF_DIR_SUFFIXES))
        man.set("crawl_leaf_formats", bool(args.crawl_leaf_formats))

        def visit(task: tuple[str, int]) -> dict:
            path, depth = task
            subdirs, files = store.list_dir(path)
            return {"path": path, "depth": depth,
                    "subdirs": subdirs, "files": files}

        frontier: list[tuple[str, int]] = [(args.prefix.strip("/"), 0)]
        with seen_lock:
            seen.add(frontier[0][0])

        while frontier:
            depth = frontier[0][1]
            batch, frontier = frontier, []
            for res in parallel_map(visit, batch, workers=args.workers,
                                    label=f"depth {depth}"):
                if not res.ok:
                    man.count("list_errors")
                    w_dirs.write({"path": res.item[0], "depth": res.item[1],
                                  "error": res.error})
                    continue
                r = res.value
                man.count("dirs_listed")
                fileset = set(r["files"])
                here = posixpath.basename(r["path"])
                # is *this* directory itself a zarr root?
                self_is_zarr = (".zgroup" in fileset or "zarr.json" in fileset
                                or looks_like_zarr_name(here))
                w_dirs.write({"path": r["path"], "depth": r["depth"],
                              "n_subdirs": len(r["subdirs"]),
                              "n_files": len(r["files"]),
                              "is_zarr_root": self_is_zarr})
                if self_is_zarr:
                    rec = {"root": r["path"], "depth": r["depth"],
                           "detected_by": ".zgroup/zarr.json" if
                           (".zgroup" in fileset or "zarr.json" in fileset) else "name"}
                    w_roots.write(rec)
                    roots.append(rec)
                    man.count("zarr_roots")
                    continue  # never descend into a zarr tree

                if r["depth"] >= args.max_depth:
                    man.count("depth_capped")
                    continue

                in_segment_parent = here in SEGMENT_PARENTS

                for d in r["subdirs"]:
                    child = posixpath.join(r["path"], d) if r["path"] else d

                    # --- zarr detection ALWAYS precedes pruning -------------
                    if looks_like_zarr_name(d):
                        rec = {"root": child, "depth": r["depth"] + 1,
                               "detected_by": "name"}
                        w_roots.write(rec)
                        roots.append(rec)
                        man.count("zarr_roots")
                        continue

                    # --- rule 3: housekeeping ------------------------------
                    if d in SKIP_NAMES:
                        man.count("pruned_skip_name")
                        continue
                    # --- rule 1: chunk / patch coordinate dirs -------------
                    if is_coordinate_dir_name(d):
                        man.count("pruned_coordinate_dir")
                        continue
                    # --- rule 4: leaf-format artifact dirs -----------------
                    if not args.crawl_leaf_formats and is_leaf_format_dir(d):
                        man.count("pruned_leaf_format")
                        continue
                    # --- rule 2: segment folders under paths/ --------------
                    if (in_segment_parent and not args.crawl_segments
                            and is_timestamp_prefixed(d)):
                        man.count("pruned_segment_dir")
                        continue

                    with seen_lock:
                        if child in seen:
                            continue
                        seen.add(child)
                    frontier.append((child, r["depth"] + 1))

        c = man.data["counters"]
        man.set("zarr_roots_found", len(roots))
        man.add_output(roots_path, "one record per Zarr root")
        man.add_output(dirs_path, "one record per directory listed")
        print(f"\nzarr roots found     : {len(roots)}")
        print(f"dirs listed          : {c.get('dirs_listed', 0)}")
        print(f"list errors          : {c.get('list_errors', 0)}")
        print(f"pruned coordinate    : {c.get('pruned_coordinate_dir', 0)}")
        print(f"pruned segment       : {c.get('pruned_segment_dir', 0)}")
        print(f"pruned leaf-format   : {c.get('pruned_leaf_format', 0)}")
        print(f"pruned skip-name     : {c.get('pruned_skip_name', 0)}")
        print(f"depth capped         : {c.get('depth_capped', 0)}")
        print(f"roots  -> {roots_path}")
        print(f"dirs   -> {dirs_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
