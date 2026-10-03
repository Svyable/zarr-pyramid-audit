"""
compare_baselines.py -- what do existing tools say about each fixture?

Runs four readers over every on-disk case in fixtures/zarr/ and records
what each one *tells its user*:

  zarr-python      open the group and read every declared level in full,
                   the way a training/data loader would. Outcome: "raises"
                   (some error surfaced) or "silent" (data returned, no
                   signal of any kind).
  ome-zarr-models  the OME-NGFF metadata validator (pydantic models of the
                   0.4/0.5 spec): "rejects" or "accepts".
  yaozarrs         pydantic-only OME-NGFF validator; its validate_zarr_store()
                   (what the `yaozarrs validate` CLI runs) checks metadata
                   *and* that declared levels exist as arrays with matching
                   dimensionality: "rejects" or "accepts".
  zpa              this package: report integrity + codes, gate verdict,
                   and the sampled chunk-probe flags.

Ground truth is assigned per fixture by what it was *built* to contain
(GROUND_TRUTH below), not derived from ZPA's output:

  defect        structurally wrong; a consumer gets wrong or no data
  suspicious    structurally valid, content looks empty -- needs a human
  benign        a valid 0.4/0.5 pyramid with nothing wrong
  out-of-model  not a 0.4/0.5 multiscale pyramid at all (a bare array, a
                plain group, an OME 0.6 pyramid): refusing to validate it as
                one is correct, so it never counts as a false alarm

A tool "flags" a fixture when it gives its user any signal: zarr-python
raises, ome-zarr-models rejects, ZPA reports a non-info code or a non-PASS
integrity (the chunk-probe column also counts non-info probe codes).

    pip install ome-zarr-models 'yaozarrs[io]'   # not dependencies of this package
    python fixtures/compare_baselines.py --out-dir artifacts/<date>-baseline-comparison

The replayed-HTTP cases are not included: they exist only as recorded
responses for HttpStore, which the baselines do not use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import corpus  # noqa: E402

DEFECT, SUSPICIOUS, BENIGN, OUT_OF_MODEL = (
    "defect", "suspicious", "benign", "out-of-model")
TRUTHS = (DEFECT, SUSPICIOUS, BENIGN, OUT_OF_MODEL)

GROUND_TRUTH = {
    "clean_v2": BENIGN, "clean_v3": BENIGN,
    "missing_level": DEFECT, "level_no_chunks": DEFECT,
    "level_undeclared": DEFECT, "scale_shape_mismatch": DEFECT,
    "mixed_rounding": DEFECT, "scale_nonmonotonic": DEFECT,
    "dtype_drift": DEFECT, "fill_drift": DEFECT,
    "compressor_drift": BENIGN,          # legal, decodes fine; low/info-ish
    "separator_drift": DEFECT, "ndim_drift": DEFECT,
    "axes_mismatch": DEFECT, "degenerate_level": DEFECT,
    "chunk_exceeds_shape": BENIGN,
    "physical_scale_unknown": BENIGN,
    "physical_scale_contradiction_units": DEFECT,
    "physical_scale_contradiction_scale": DEFECT,
    "physical_scale_unspecified": BENIGN,
    "ome_version_unmodelled": OUT_OF_MODEL,
    "transform_scale_count": DEFECT, "transform_arity": DEFECT,
    "axes_invalid": DEFECT, "dimension_names_missing": DEFECT,
    "multiscale_empty": DEFECT, "not_multiscale": OUT_OF_MODEL,
    "bare_array": OUT_OF_MODEL, "headerless_chunk_store": DEFECT,
    "container_no_group_header": DEFECT, "not_a_zarr_group": OUT_OF_MODEL,
    "root_absent": DEFECT,
    "malformed_zgroup": DEFECT, "malformed_zattrs": DEFECT,
    "malformed_level_header": DEFECT,
    "present_all_fill": SUSPICIOUS, "zero_data_nonzero_fill": BENIGN,
    "nan_fill_all_empty": SUSPICIOUS, "all_fill_nonzero": SUSPICIOUS,
    "sparse_level": BENIGN, "sparse_unsampled": BENIGN,
    "undecodable_codec": DEFECT, "partially_empty": BENIGN,
}


def _declared_paths(attrs) -> list[str]:
    ms = attrs.get("multiscales") or (attrs.get("ome") or {}).get("multiscales")
    if not ms:
        return []
    return [str(d.get("path")) for d in ms[0].get("datasets", [])
            if isinstance(d, dict)]


def zarr_python(path: str) -> dict:
    """Open and fully read every declared level; report what surfaced."""
    import zarr
    try:
        node = zarr.open(path, mode="r")
    except Exception as exc:
        return {"outcome": "raises", "detail": f"open: {type(exc).__name__}"}
    try:
        if isinstance(node, zarr.Array):
            node[...]
            return {"outcome": "silent", "detail": "array read"}
        attrs = dict(node.attrs)
        paths = _declared_paths(attrs)
        for p in paths:
            node[p][...]
        return {"outcome": "silent",
                "detail": f"read {len(paths)} declared level(s)"}
    except Exception as exc:
        return {"outcome": "raises", "detail": f"read: {type(exc).__name__}"}


def ome_zarr_models(path: str) -> dict:
    import zarr
    from ome_zarr_models import open_ome_zarr
    try:
        model = open_ome_zarr(zarr.open_group(path, mode="r"))
    except Exception as exc:
        return {"outcome": "rejects", "detail": type(exc).__name__}
    return {"outcome": "accepts", "detail": type(model).__name__}


def yaozarrs_(path: str) -> dict:
    import yaozarrs
    try:
        yaozarrs.validate_zarr_store(path)
    except Exception as exc:
        return {"outcome": "rejects", "detail": type(exc).__name__}
    return {"outcome": "accepts", "detail": "validate_zarr_store"}


def zpa(name: str) -> dict:
    with open(os.path.join(corpus.EXPECTED_DIR, f"{name}.json"), encoding="utf-8") as fh:
        g = json.load(fh)
    scan_flags = sorted({c for lv in g.get("chunk_scan", [])
                         for c in lv["level_codes"]})
    return {"integrity": g["integrity"], "gate": g["gate"]["verdict"],
            "codes": sorted({f["code"] for f in g["findings"]}),
            "scan_flags": scan_flags}


def flagged(row: dict) -> dict:
    """Did each tool give its user *any* signal for this fixture?"""
    from zpa.audit_pyramid import SEVERITY
    from zpa.chunkscan import SCAN_SEVERITY
    z = row["zpa"]
    header = (z["integrity"] != "PASS"
              or any(SEVERITY[c] != "info" for c in z["codes"]))
    probe = any(SCAN_SEVERITY[c] != "info" for c in z["scan_flags"])
    return {
        "zarr-python": row["zarr_python"]["outcome"] == "raises",
        "ome-zarr-models": row["ome_zarr_models"]["outcome"] == "rejects",
        "yaozarrs": row["yaozarrs"]["outcome"] == "rejects",
        "zpa (header audit)": header,
        "zpa (+ chunk probe)": header or probe,
    }


def run() -> list[dict]:
    warnings.filterwarnings("ignore")
    rows = []
    for name, prop, _ in corpus.ZARR_CASES:
        path = os.path.join(corpus.ZARR_DIR, f"{name}.zarr")
        row = {"fixture": name, "property": prop, "truth": GROUND_TRUTH[name],
               "zarr_python": zarr_python(path),
               "ome_zarr_models": ome_zarr_models(path),
               "yaozarrs": yaozarrs_(path),
               "zpa": zpa(name)}
        row["flagged"] = flagged(row)
        rows.append(row)
    return rows


TOOLS = ["zarr-python", "ome-zarr-models", "yaozarrs", "zpa (header audit)", "zpa (+ chunk probe)"]


def summary(rows: list[dict]) -> dict:
    def hit(r, tool):
        # For out-of-model nodes the question is "did the tool say what this
        # is?": ZPA's info codes (BARE_ARRAY, NOT_MULTISCALE, ...) count.
        if r["truth"] == OUT_OF_MODEL and tool.startswith("zpa"):
            return r["flagged"][tool] or bool(r["zpa"]["codes"])
        return r["flagged"][tool]

    out = {}
    for tool in TOOLS:
        out[tool] = {
            truth: {"flagged": sum(1 for r in rows if r["truth"] == truth
                                   and hit(r, tool)),
                    "of": sum(1 for r in rows if r["truth"] == truth)}
            for truth in TRUTHS}
    return out


def markdown(rows: list[dict], summ: dict, versions: dict) -> str:
    lines = [
        "| tool | defects flagged | suspicious content flagged | false alarms on valid pyramids | out-of-model nodes identified |",
        "|---|---|---|---|---|",
    ]
    for tool in TOOLS:
        s = summ[tool]
        lines.append(f"| {tool} | {s[DEFECT]['flagged']} / {s[DEFECT]['of']} | "
                     f"{s[SUSPICIOUS]['flagged']} / {s[SUSPICIOUS]['of']} | "
                     f"{s[BENIGN]['flagged']} / {s[BENIGN]['of']} | "
                     f"{s[OUT_OF_MODEL]['flagged']} / {s[OUT_OF_MODEL]['of']} |")
    lines += ["", "Per fixture (✓ = the tool gave its user a signal):", "",
              "| fixture | truth | zarr-python | ome-zarr-models | yaozarrs | ZPA integrity / codes | ZPA chunk probe |",
              "|---|---|---|---|---|---|---|"]
    mark = {True: "✓", False: "·"}
    for r in rows:
        z = r["zpa"]
        lines.append(
            f"| `{r['fixture']}` | {r['truth']} | "
            f"{mark[r['flagged']['zarr-python']]} {r['zarr_python']['outcome']} | "
            f"{mark[r['flagged']['ome-zarr-models']]} {r['ome_zarr_models']['outcome']} | "
            f"{mark[r['flagged']['yaozarrs']]} {r['yaozarrs']['outcome']} | "
            f"{z['integrity']} {', '.join(z['codes']) or '—'} | "
            f"{', '.join(z['scan_flags']) or '—'} |")
    lines += ["", "Versions: " + ", ".join(f"{k} {v}" for k, v in versions.items())]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    import ome_zarr_models as ozm
    import yaozarrs
    import zarr
    from importlib.metadata import version
    versions = {"zarr": zarr.__version__, "ome-zarr-models": ozm.__version__,
                "yaozarrs": yaozarrs.__version__,
                "zarr-pyramid-audit": version("zarr-pyramid-audit"),
                "fixture corpus": corpus.CORPUS_VERSION}
    rows = run()
    summ = summary(rows)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "comparison.json"), "w", encoding="utf-8") as fh:
        json.dump({"versions": versions, "summary": summ, "rows": rows}, fh,
                  indent=2, sort_keys=True)
        fh.write("\n")
    md = markdown(rows, summ, versions)
    with open(os.path.join(args.out_dir, "comparison.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
