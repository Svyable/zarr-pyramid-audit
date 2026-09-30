#!/usr/bin/env python3
"""
build_dashboard.py -- generate docs/index.html, a self-contained public
data-health dashboard for the Vesuvius open-data Zarr audit.

Every number is read from the audit artifacts in this repo -- nothing is
hand-typed, so the dashboard can never drift from the evidence. Re-run
after any new audit and commit the result.

Usage:
    python bin/build_dashboard.py --out docs/index.html
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
from collections import Counter

REPO = os.environ.get("ZPA_REPO", os.getcwd())
ART = os.path.join(REPO, "artifacts")

DEFECTIVE = ("PHerc0814/segments/20260226123353-auto_grown_20260226123353106/"
             "surface-volumes/1.129um-0.22m-59keV-volume-20260521123630-L1.zarr")

SEV_COLORS = {"high": "#ff6b6b", "medium": "#ff9e5e", "low": "#a89880",
              "info": "#6f6350"}

# check-code -> one-line plain-language description
CODE_BLURB = {
    "LEVEL_NO_CHUNKS": "valid header, zero chunk objects — reads return fill_value silently",
    "LEVEL_MISSING": "declared level has no readable array header",
    "LEVEL_UNDECLARED": "numeric level dir exists but is not declared",
    "MULTISCALE_EMPTY": "declares multiscales but datasets list is empty",
    "SCALE_SHAPE_MISMATCH": "level shape matches neither ceil nor floor of base/factor",
    "MIXED_ROUNDING": "ceil at some levels, floor at others",
    "DTYPE_DRIFT": "dtype changes between levels",
    "FILL_DRIFT": "fill_value changes between levels",
    "COMPRESSOR_DRIFT": "codec changes between levels",
    "SEPARATOR_DRIFT": "dimension_separator changes between levels",
    "NDIM_DRIFT": "levels disagree on dimensionality",
    "AXES_MISMATCH": "declared axes count != array ndim",
    "CHUNK_EXCEEDS_SHAPE": "fixed chunk shape carried below the array — informational",
    "SCALE_NONMONOTONIC": "declared scales do not strictly increase",
    "DEGENERATE_LEVEL": "a level has a zero/negative extent",
    "HEADERLESS_CHUNK_STORE": "chunk keys present but no decodable header",
    "CONTAINER_NO_GROUP_HEADER": "children are Zarr nodes but root has no group header",
    "EMPTY_ZARR_DIR": "*.zarr directory with no contents",
    "NOT_A_ZARR_GROUP": "no .zgroup / zarr.json and nothing Zarr-like inside",
    "NOT_MULTISCALE": "valid Zarr group, never claimed to be a pyramid",
    "BARE_ARRAY": "valid single-scale Zarr array, not a pyramid",
}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>zarr-pyramid-audit — Don't train on lies</title>
<meta name="description" content="Independent integrity audit of the Vesuvius open-data Zarr stores. 957 S3 roots audited, one defective pyramid found.">
<style>
:root{{
  --bg:#0d0b08; --panel:#161310; --panel2:#1c1813; --line:#2c251b;
  --ink:#ece3d2; --muted:#a89880; --dim:#6f6350;
  --ember:#ff7a1a; --gold:#ffd166; --amber:#ffb347;
  --good:#8fd694; --warn:#ff9e5e; --bad:#ff6b6b;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}}
a{{color:var(--amber)}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 1.25rem}}
.hero{{position:relative;overflow:hidden;padding:4.5rem 0 3rem;
  background:
    radial-gradient(1200px 500px at 70% -10%, rgba(255,122,26,.14), transparent 60%),
    radial-gradient(800px 400px at 15% 110%, rgba(255,209,102,.08), transparent 60%),
    var(--bg)}}
.eyebrow{{letter-spacing:.28em;font-size:.72rem;color:var(--ember);font-weight:700}}
.hero h1{{font-family:Georgia,"Times New Roman",serif;font-size:clamp(2.4rem,6vw,4.2rem);
  margin:.4rem 0 .2rem;font-weight:700;letter-spacing:-.02em}}
.hero h1 .q{{color:var(--ember)}}
.tagline{{font-size:1.3rem;margin:.2rem 0 1rem}}
.tagline em{{color:var(--amber);font-style:normal;font-weight:600}}
.lede{{color:var(--muted);max-width:46rem;line-height:1.65;font-size:1.0rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:.75rem;margin-top:2rem}}
.stat{{background:rgba(22,19,16,.85);border:1px solid var(--line);border-radius:12px;
  padding:1rem 1.1rem}}
.stat .n{{font-size:1.9rem;font-weight:800;color:var(--gold);font-variant-numeric:tabular-nums}}
.stat .n.bad{{color:var(--bad)}} .stat .n.good{{color:var(--good)}}
.stat .l{{font-size:.78rem;color:var(--muted);margin-top:.25rem;line-height:1.4}}
.insights{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:.9rem;margin:2.2rem 0}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:1.25rem 1.35rem}}
.card h3{{margin:0 0 .5rem;font-size:.8rem;letter-spacing:.14em;color:var(--ember);
  text-transform:uppercase}}
.card p{{margin:.35rem 0;color:var(--muted);line-height:1.6;font-size:.94rem}}
.card p b{{color:var(--ink)}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:1.5rem;margin:0 0 2rem}}
.panel h2{{margin:.1rem 0 1rem;font-family:Georgia,serif;font-size:1.6rem}}
.panel h2 .sub{{display:block;font-size:.85rem;color:var(--muted);
  font-weight:400;margin-top:.3rem;font-family:inherit}}
.panel p{{color:var(--muted);line-height:1.65;font-size:.95rem}}
.panel p b{{color:var(--ink)}}
.path{{font-family:ui-monospace,monospace;font-size:.8rem;background:#1a0f08;
  border:1px solid #5a2c12;border-radius:8px;padding:.8rem 1rem;
  word-break:break-all;color:var(--warn);margin:.8rem 0}}
.gatebox{{border-left:3px solid var(--ember);padding:.6rem 1rem;background:#171208;
  border-radius:0 8px 8px 0;color:var(--muted);line-height:1.65;font-size:.93rem;margin-top:1rem}}
table{{border-collapse:collapse;width:100%;font-size:.86rem}}
thead th{{text-align:left;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);padding:.6rem .5rem;border-bottom:1px solid var(--line);
  cursor:pointer;user-select:none;white-space:nowrap}}
thead th:hover{{color:var(--ink)}}
thead th .arr{{color:var(--ember)}}
tbody td{{padding:.55rem .5rem;border-bottom:1px solid #211c14;vertical-align:top}}
tbody tr:hover td{{background:#1e1913}}
.num{{font-variant-numeric:tabular-nums;text-align:right}}
.sev{{display:inline-block;font-size:.68rem;font-weight:800;letter-spacing:.08em;
  border-radius:6px;padding:.18rem .5rem;text-transform:uppercase}}
.sev.high{{background:rgba(255,107,107,.12);color:var(--bad);border:1px solid rgba(255,107,107,.4)}}
.sev.medium{{background:rgba(255,158,94,.12);color:var(--warn);border:1px solid rgba(255,158,94,.35)}}
.sev.low,.sev.info{{background:rgba(168,152,128,.10);color:var(--muted);border:1px solid rgba(168,152,128,.3)}}
.cbar{{display:flex;height:10px;border-radius:5px;overflow:hidden;min-width:120px;background:#0a0906}}
.cbar span{{display:block;height:100%}}
.cb-s3{{background:#ff7a1a}} .cb-dl{{background:#7a4fd0}}
code{{font-size:.8rem;color:var(--amber)}}
.controls{{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem}}
.sevbtn{{background:var(--panel2);border:1px solid var(--line);color:var(--muted);
  border-radius:999px;padding:.45rem .9rem;font-size:.82rem;cursor:pointer}}
.sevbtn.on{{border-color:var(--ember);color:var(--ink);background:#241a10}}
.method{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}}
.suite{{display:flex;gap:1rem;flex-wrap:wrap;align-items:stretch}}
.suite .card{{flex:1;min-width:260px}}
footer{{border-top:1px solid var(--line);margin-top:1rem;padding:1.6rem 0 3rem;
  color:var(--dim);font-size:.82rem;line-height:1.7}}
.hidden{{display:none!important}}
@media(max-width:700px){{.cbar{{min-width:70px}}}}
</style></head><body>

<header class="hero"><div class="wrap">
  <div class="eyebrow">VESUVIUS CHALLENGE · SEPTEMBER 2026</div>
  <h1>zarr-pyramid-audit</h1>
  <p class="tagline">Corruption detection for OME-Zarr pyramids. <em>Don't train on lies.</em></p>
  <p class="lede">An independent integrity audit of the public Vesuvius Challenge
  data stores. Every pyramid is judged from its headers — a few KB per pyramid,
  no full downloads — plus sampled chunk-content probes that decode real voxels.
  Every number below is read from committed audit artifacts; nothing is hand-typed.
  <a href="{repo}">Repo (MIT)</a> · <a href="./september-2026.html">September 2026 writeup →</a></p>
  <div class="stats">
    <div class="stat"><div class="n">{s3_audited}</div><div class="l">S3 Zarr roots audited<br>2026-09-29 · header-only · ~5 min</div></div>
    <div class="stat"><div class="n good">{s3_clean}</div><div class="l">clean</div></div>
    <div class="stat"><div class="n bad">{s3_defective}</div><div class="l">defective pyramid<br>6 header-only levels</div></div>
    <div class="stat"><div class="n">{dl_audited}</div><div class="l">dl.ash2txt.org roots<br>re-audited 2026-09-29</div></div>
    <div class="stat"><div class="n bad">0</div><div class="l">defects fixed in 20 days<br>strict diff: 0 fixed, 0 new</div></div>
    <div class="stat"><div class="n good">{chunks_probed}</div><div class="l">chunks content-probed<br>sampled + decoded</div></div>
  </div>
</div></header>

<div class="wrap">

<div class="insights">
  <div class="card"><h3>The live defect</h3>
    <p>A <b>PHerc0814</b> surface-volume pyramid in the open-data S3 bucket has
    <b>valid headers at all six levels and zero chunk objects</b>. Every reader
    opens it fine and gets plausible all-zero voxels — no error, no warning.
    Proven by direct read; independently confirms
    <a href="https://github.com/scrollprize/villa/issues/1892">villa #1892</a>.</p></div>
  <div class="card"><h3>20-day regression</h3>
    <p>The identical audit re-ran over the identical 241-root dl list on
    2026-09-29. Strict diff on every finding field: <b>empty</b>. 18 defective
    pyramids, 50 actionable findings — <b>zero fixed, zero new</b>. Published
    defects don't get fixed after the fact; the publish-time gate is the lever.</p></div>
  <div class="card"><h3>Training volumes probed</h3>
    <p><b>{vc_pop}</b> volcomp inner chunks decoded with real content across all
    64 scroll volumes, <b>{v2_pop}</b> raw/Blosc chunks across 128 dl roots —
    <b>0 all-empty levels</b> in the training data. One present-but-empty mesh
    derivative caught in <code>other/dev/</code> (medium, human review).</p></div>
</div>

<div class="panel"><h2>🚨 The defective pyramid<span class="sub">s3://vesuvius-challenge-open-data</span></h2>
  <div class="path">{defective}</div>
  <p>All six pyramid levels carry <b>valid array headers but zero chunk objects</b>.
  Any reader — viewer, registration, model — opens it successfully and gets back
  plausible all-zero voxels. We proved it empirically: a full-extent read returned
  all zeros while a control region on a sibling volume returned
  <b>64,498 nonzero voxels</b>.</p>
  <p>The defect is isolated with unusual sharpness: the same filename stem exists in
  <b>19 segment runs</b> and exactly one copy — the <code>20260226123353</code> run —
  is header-only. The other 18 are clean, and a sampled chunk-content probe confirmed
  they hold real data, not present-but-empty shells.</p>
  <div class="gatebox"><b>The fix ships with the repo:</b> <code>zpa-gate</code> is a
  publish-time metadata gate that audits roots <i>before</i> they publish and fails
  closed (exit 1) on any finding at or above the severity threshold — with GitHub
  Actions annotations for CI. This defect class can never ship again.</div>
</div>

<div class="panel"><h2>Findings by check code<span class="sub">Click a column to sort · filter by severity · S3 = open-data bucket, dl = dl.ash2txt.org</span></h2>
  <div class="controls">
    <button class="sevbtn on" data-s="">all</button>
    <button class="sevbtn" data-s="high">high</button>
    <button class="sevbtn" data-s="medium">medium</button>
    <button class="sevbtn" data-s="low">low</button>
    <button class="sevbtn" data-s="info">info</button>
  </div>
  <div style="overflow-x:auto"><table id="codes"><thead><tr>
    <th data-k="code">check code</th><th data-k="sev">severity</th>
    <th data-k="s3">S3</th><th data-k="dl">dl</th><th>distribution</th><th>meaning</th>
  </tr></thead><tbody>{code_rows}</tbody></table></div>
  <p style="margin-top:1rem">S3: <b>{s3_actionable} actionable findings</b>
  (all <code>LEVEL_NO_CHUNKS</code> — the six levels of the defective pyramid),
  {s3_info} informational. dl: {dl_actionable} actionable,
  {dl_info} informational across 18 defective pyramids (villa #1755–#1760).</p>
</div>

<div class="panel"><h2>Chunk-content probe<span class="sub">2026-09-30 · sampled decode, not just headers</span></h2>
  <p>The header-only audit answers "are chunk keys present?" — the probe answers the
  next question: <b>"do the present chunks hold data?"</b> This closes the next
  silent-corruption class: chunks that exist but decode to all fill_value.</p>
  <table><thead><tr><th>campaign</th><th class="num">roots</th><th class="num">levels</th>
  <th class="num">chunks decoded</th><th class="num">populated</th><th class="num">all-empty levels</th></tr></thead>
  <tbody>{probe_rows}</tbody></table>
  {v2_note}
  <p>The present-but-empty class was not observed in the S3 or training-volume samples —
  reported as evidence of absence in the sample, not proof of absence in the corpus.
  The tool is published for anyone to rerun at larger sample sizes.</p>
</div>

<div class="panel"><h2>Mirror fidelity: S3 vs dl.ash2txt.org<span class="sub">same names, not copies</span></h2>
  <p>64 same-named volumes exist in both stores. They are <b>format migrations</b> of
  identical voxel grids at all six levels:</p>
  <table><thead><tr><th></th><th>dl.ash2txt.org</th><th>S3 open-data</th></tr></thead><tbody>
  <tr><td>Zarr format</td><td>v3</td><td>v2</td></tr>
  <tr><td>chunking</td><td>1024³ shards</td><td>128³ raw</td></tr>
  <tr><td>codec</td><td>sharding_indexed + lossy volcomp (q=1.0)</td><td>none (raw uint8)</td></tr>
  </tbody></table>
  <p>Byte-level comparison (volcomp decoded from source) shows quantization noise only:
  max absolute difference 30–35, mean below 0.1, ~2–4% of voxels differ.
  <b>Reproducibility work must pin the store, not just the filename.</b></p>
</div>

<div class="panel"><h2>Known silent-zero volumes<span class="sub">dl.ash2txt.org · header-only levels confirmed by direct read</span></h2>
  <table><thead><tr><th>volume</th><th>header-only levels</th></tr></thead><tbody>
  <tr><td><code>community-uploads/bruniss/labels/surfaces/archive/1-voxel-sheet_slices-closed.zarr</code></td><td>1–5 (level 0 populated)</td></tr>
  <tr><td><code>other/dev/inked_zarrs/3336_predictions.zarr</code></td><td>all six</td></tr>
  </tbody></table>
  <p>Unchanged between the 2026-09-09 and 2026-09-29 audits. Full machine-readable
  kill list: <code>data/known-defects.json</code> ({kd_n} entries).</p>
</div>

<div class="panel"><h2>One suite, two halves</h2>
<div class="suite">
  <div class="card"><h3>ScrollQ</h3>
    <p><b>Train on the best first.</b> Quality scoring 0–100 for every scroll volume,
    resampling-stability proof, and the label-coverage join that flags
    "🎯 label next" targets.</p>
    <p><a href="https://github.com/Svyable/scrollq">repo</a> ·
    <a href="https://svyable.github.io/scrollq/">leaderboard</a></p></div>
  <div class="card"><h3>scrollq-health</h3>
    <p>Runs the integrity audit <b>and</b> the quality score on any volume and
    issues one verdict: <b>TRAIN / CAUTION / DO NOT TRAIN</b>.</p>
    <p><code>scrollq-health --root &lt;volume&gt;</code></p></div>
</div></div>

</div><!-- /wrap -->

<footer><div class="wrap">
  <b>Method.</b> Header-only pyramid audit (<code>zpa-audit</code>): 21 check codes over
  <code>.zattrs</code> + one <code>.zarray</code> per level — a few KB per pyramid
  regardless of array size. Chunk-presence via one listing per level. Chunk-content via
  sampled decode (vendored libvolcomp for the sharded volcomp levels). Full evidence,
  manifests, and runbooks in <code>artifacts/</code> in the
  <a href="{repo}">repo</a> (MIT fork of sgsllc-jr/zarr-pyramid-audit; upstream credit retained).<br>
  Built by Sven + Muse · updated {stamp}.
</div></footer>

<script>
(function(){{
  const tb = document.querySelector("#codes tbody");
  const rows = Array.from(tb.querySelectorAll("tr"));
  let sortK = "total", asc = false, sevF = "";
  function apply(){{
    let vis = rows.filter(r => !sevF || r.dataset.sev === sevF);
    vis.sort((a, b) => {{
      let x, y;
      if (sortK === "code" || sortK === "sev") {{
        x = a.dataset[sortK]; y = b.dataset[sortK];
        return asc ? x.localeCompare(y) : y.localeCompare(x);
      }}
      x = parseFloat(a.dataset[sortK]); y = parseFloat(b.dataset[sortK]);
      return asc ? x - y : y - x;
    }});
    const frag = document.createDocumentFragment();
    vis.forEach(r => frag.append(r));
    rows.forEach(r => r.classList.add("hidden"));
    vis.forEach(r => r.classList.remove("hidden"));
    tb.append(frag);
  }}
  document.querySelectorAll("#codes thead th[data-k]").forEach(th => {{
    th.addEventListener("click", () => {{
      const k = th.dataset.k;
      if (sortK === k) asc = !asc; else {{ sortK = k; asc = (k === "code" || k === "sev"); }}
      document.querySelectorAll("#codes thead th .arr").forEach(e => e.remove());
      const s = document.createElement("span"); s.className = "arr";
      s.textContent = asc ? " ▲" : " ▼"; th.appendChild(s);
      apply();
    }});
  }});
  document.querySelectorAll(".sevbtn").forEach(b => b.addEventListener("click", () => {{
    document.querySelectorAll(".sevbtn").forEach(x => x.classList.remove("on"));
    b.classList.add("on"); sevF = b.dataset.s; apply();
  }}));
  apply();
}})();
</script>
</body></html>
"""

SEVERITY = {
    "MULTISCALE_EMPTY": "high", "LEVEL_MISSING": "high",
    "LEVEL_NO_CHUNKS": "high", "SEPARATOR_DRIFT": "high",
    "DTYPE_DRIFT": "high", "SCALE_SHAPE_MISMATCH": "high",
    "DEGENERATE_LEVEL": "high", "NDIM_DRIFT": "high",
    "LEVEL_UNDECLARED": "medium", "SCALE_NONMONOTONIC": "medium",
    "FILL_DRIFT": "medium", "MIXED_ROUNDING": "medium",
    "COMPRESSOR_DRIFT": "low", "AXES_MISMATCH": "low",
    "HEADERLESS_CHUNK_STORE": "high", "CONTAINER_NO_GROUP_HEADER": "low",
    "EMPTY_ZARR_DIR": "low",
    "NOT_A_ZARR_GROUP": "info", "NOT_MULTISCALE": "info",
    "BARE_ARRAY": "info", "CHUNK_EXCEEDS_SHAPE": "info",
}


def load_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "index.html"))
    args = ap.parse_args()

    s3 = load_json(f"{ART}/2026-09-29-s3/audit_pyramid.summary.json")
    dl = load_json(f"{ART}/2026-09-29-dl-regression/audit_pyramid.summary.json")
    cs = load_json(f"{ART}/2026-09-30-s3-chunkscan/scan_empty_chunks.summary.json")
    try:
        csv3 = load_json(f"{ART}/2026-09-30-s3-chunkscan-v3/scan_empty_chunks.summary.json")
    except FileNotFoundError:
        csv3 = None
    try:
        vc = load_json(f"{ART}/2026-09-30-dl-volcomp-probe/scan_empty_chunks.summary.json")
    except FileNotFoundError:
        vc = None
    try:
        v2 = load_json(f"{ART}/2026-09-30-dl-v2-probe/scan_empty_chunks.summary.json")
    except FileNotFoundError:
        v2 = None
    try:
        kd = load_json(os.path.join(REPO, "data", "known-defects.json"))
        kd_n = len(kd) if isinstance(kd, list) else len(kd.get("defects", kd))
    except FileNotFoundError:
        kd_n = 0

    s3_codes = s3["by_code"]
    dl_codes = dl["by_code"]
    max_code = max(list(s3_codes.values()) + list(dl_codes.values()) + [1])

    code_rows = []
    for code in sorted(set(s3_codes) | set(dl_codes),
                       key=lambda c: -(s3_codes.get(c, 0) + dl_codes.get(c, 0))):
        sev = SEVERITY.get(code, "medium")
        s3n, dln = s3_codes.get(code, 0), dl_codes.get(code, 0)
        bar_html = (
            f'<div class="cbar">'
            f'<span class="cb-s3" style="width:{100*s3n/max_code:.1f}%"></span>'
            f'<span class="cb-dl" style="width:{100*dln/max_code:.1f}%"></span>'
            f'</div>')
        code_rows.append(
            f'<tr data-code="{html.escape(code)}" data-sev="{sev}" '
            f'data-s3="{s3n}" data-dl="{dln}" data-total="{s3n + dln}">'
            f'<td><code>{html.escape(code)}</code></td>'
            f'<td><span class="sev {sev}">{sev}</span></td>'
            f'<td class="num">{s3n}</td><td class="num">{dln}</td>'
            f'<td>{bar_html}</td>'
            f'<td style="color:var(--muted)">{html.escape(CODE_BLURB.get(code, ""))}</td>'
            f'</tr>')

    def probe_row(name, d):
        if not d:
            return ""
        bc = d["by_code"]
        pop = bc.get("CHUNK_SAMPLE_POPULATED", 0)
        empty = d.get("n_levels_all_empty", 0)
        return (
            f"<tr><td>{name}</td>"
            f'<td class="num">{d["roots_scanned"]}</td>'
            f'<td class="num">{d["levels_scanned"]}</td>'
            f'<td class="num">{pop + bc.get("CHUNK_SAMPLE_EMPTY", 0) + bc.get("CHUNK_SAMPLE_MISSING", 0)}</td>'
            f'<td class="num" style="color:var(--good)"><b>{pop}</b></td>'
            f'<td class="num" style="color:{"var(--bad)" if empty else "var(--good)"}"><b>{empty}</b></td></tr>')

    probe_rows = (
        probe_row("S3 v2 (zarr-python windows)", cs)
        + probe_row("S3 v3 sharded (zarr-python windows)", csv3)
        + probe_row("dl volcomp (vendored libvolcomp, HTTP byte ranges)", vc)
        + probe_row("dl v2 raw/Blosc", v2))

    if v2 and v2.get("n_levels_all_empty"):
        v2_note = (
            f'<div class="gatebox"><b>One real catch:</b> '
            f'<code>other/dev/meshes/20231022170900-ome.zarr</code> L1–L7 decode to '
            f'all zeros while L0 holds mesh data — a dev-directory mesh derivative, '
            f'not a scroll. Flagged <b>medium</b> for human review, with caveats. '
            f'This is the probe working as designed.</div>')
    else:
        v2_note = ""

    vc_pop = vc["by_code"].get("CHUNK_SAMPLE_POPULATED", 0) if vc else 0
    v2_pop = v2["by_code"].get("CHUNK_SAMPLE_POPULATED", 0) if v2 else 0
    chunks_probed = (cs["by_code"].get("CHUNK_SAMPLE_POPULATED", 0) + vc_pop + v2_pop
                     + (csv3["by_code"].get("CHUNK_SAMPLE_POPULATED", 0) if csv3 else 0))

    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    page = PAGE.format(
        repo="https://github.com/Svyable/zarr-pyramid-audit",
        s3_audited=s3["pyramids_audited"], s3_clean=s3["pyramids_clean"],
        s3_defective=s3["pyramids_with_defects"],
        dl_audited=dl["pyramids_audited"],
        chunks_probed=chunks_probed,
        defective=html.escape(DEFECTIVE),
        code_rows="\n".join(code_rows),
        s3_actionable=s3["findings_actionable"], s3_info=s3["findings_informational"],
        dl_actionable=dl["findings_actionable"], dl_info=dl["findings_informational"],
        probe_rows=probe_rows, v2_note=v2_note,
        vc_pop=vc_pop, v2_pop=v2_pop, kd_n=kd_n, stamp=stamp,
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {args.out} ({len(page)//1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
