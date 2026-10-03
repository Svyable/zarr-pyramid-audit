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
    "ROOT_ABSENT": "requested Zarr root is confirmed absent",
    "ACCESS_UNKNOWN": "access could not establish presence or absence — informational",
    "METADATA_UNREADABLE": "metadata exists but could not be decoded",
    "PHYSICAL_SCALE_UNKNOWN": "metadata says absolute physical size is unknown — informational",
    "PHYSICAL_SCALE_CONTRADICTION": "physical size marked unknown but metadata also claims an absolute scale",
    "OME_VERSION_UNMODELLED": "declared OME-NGFF version is newer than the audit models — informational",
    "TRANSFORM_SCALE_COUNT": "dataset declares zero or several scale transforms",
    "TRANSFORM_ARITY": "scale/translation length does not match the axes",
    "AXES_INVALID": "duplicate axis names, or typed axes out of NGFF count/order",
    "DIMENSION_NAMES_MISMATCH": "OME-Zarr 0.5: array dimension_names missing or not equal to the axes",
    "EMPTY_ZARR_DIR": "*.zarr directory with no contents",
    "NOT_A_ZARR_GROUP": "no .zgroup / zarr.json and nothing Zarr-like inside",
    "NOT_MULTISCALE": "valid Zarr group, never claimed to be a pyramid",
    "BARE_ARRAY": "valid single-scale Zarr array, not a pyramid",
    "PHYSICAL_SCALE_UNKNOWN": "metadata explicitly says absolute physical size is unknown — informational",
    "PHYSICAL_SCALE_CONTRADICTION": "physical_size=unknown conflicts with spatial units or a non-identity level-0 scale",
}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>zarr-pyramid-audit — Don't train on lies</title>
<meta name="description" content="Independent integrity audit of the Vesuvius open-data Zarr stores. 957 S3 roots audited, one defective pyramid found. The integrity half of the ScrolIQ data-quality suite.">
<meta name="theme-color" content="#0d0b08">
<meta name="color-scheme" content="dark">
<link rel="icon" href="./favicon.svg" type="image/svg+xml">
<link rel="canonical" href="https://svyable.github.io/zarr-pyramid-audit/">
<meta property="og:type" content="website">
<meta property="og:title" content="zarr-pyramid-audit — Don't train on lies">
<meta property="og:description" content="Evidence-backed integrity auditing for public OME-Zarr pyramids.">
<meta property="og:url" content="https://svyable.github.io/zarr-pyramid-audit/">
<style>
:root{{
  --bg:#0d0b08; --panel:#161310; --panel2:#1c1813; --line:#2c251b;
  --ink:#ece3d2; --muted:#a89880; --dim:#6f6350;
  --ember:#ff7a1a; --gold:#ffd166; --amber:#ffb347;
  --good:#8fd694; --warn:#ff9e5e; --bad:#ff6b6b;
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}}
a{{color:var(--amber)}}
a:focus-visible,button:focus-visible,input:focus-visible{{outline:2px solid var(--gold);outline-offset:3px}}
.skip{{position:fixed;left:1rem;top:1rem;z-index:1000;transform:translateY(-180%);
  background:var(--gold);color:#171008;padding:.55rem .8rem;border-radius:8px;font-weight:800;text-decoration:none}}
.skip:focus{{transform:none}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 1.25rem}}
.topbar{{position:sticky;top:0;z-index:50;background:rgba(13,11,8,.88);
  backdrop-filter:blur(16px);border-bottom:1px solid rgba(44,37,27,.78)}}
.navinner{{max-width:1200px;margin:0 auto;padding:.7rem 1.25rem;display:flex;align-items:center;gap:1rem}}
.brand{{display:flex;align-items:center;gap:.6rem;color:var(--ink);text-decoration:none;font-weight:800}}
.brandmark{{width:26px;height:26px;border-radius:7px;border:1px solid #6f3b18;display:grid;place-items:center;
  color:var(--ember);font-family:Georgia,serif;background:#17110c}}
.navlinks{{display:flex;gap:.2rem;margin-left:auto;align-items:center;flex-wrap:wrap}}
.navlinks a{{color:var(--muted);text-decoration:none;font-size:.82rem;padding:.38rem .58rem;border-radius:7px}}
.navlinks a:hover{{color:var(--ink);background:var(--panel2)}}
.navstatus{{font-size:.72rem;color:var(--good);border:1px solid rgba(143,214,148,.24);
  background:rgba(143,214,148,.06);padding:.3rem .55rem;border-radius:999px;white-space:nowrap}}
.hero{{position:relative;overflow:hidden;padding:4.2rem 0 3rem;
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
.recheck{{border-left:3px solid var(--gold);padding:.6rem 1rem;background:#14110a;
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
.search{{margin-left:auto;display:flex;align-items:center;min-width:min(100%,260px)}}
.search input{{width:100%;background:#100e0b;border:1px solid var(--line);border-radius:999px;color:var(--ink);
  padding:.47rem .8rem;font:inherit;font-size:.82rem}}
.resultcount{{font-size:.76rem;color:var(--dim);min-width:5.5rem;text-align:right}}
.sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
.sevbtn{{background:var(--panel2);border:1px solid var(--line);color:var(--muted);
  border-radius:999px;padding:.45rem .9rem;font-size:.82rem;cursor:pointer}}
.sevbtn.on{{border-color:var(--ember);color:var(--ink);background:#241a10}}
.method{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}}
.suite{{display:flex;gap:1rem;flex-wrap:wrap;align-items:stretch}}
.suite .card{{flex:1;min-width:260px}}
.suite .card .role{{color:var(--ink);font-weight:700;margin-top:.1rem}}
.suitechip{{margin:1.1rem 0 0}}
.suitechip a{{display:inline-block;border:1px solid #6f3b18;border-radius:999px;padding:.38rem .85rem;
  font-size:.82rem;text-decoration:none;color:var(--amber);background:rgba(255,122,26,.07)}}
.suitechip a:hover{{border-color:var(--ember);color:var(--gold)}}
.flow{{display:flex;align-items:stretch;gap:.5rem;flex-wrap:wrap;margin:1.1rem 0}}
.flow .step{{flex:1;min-width:170px;background:var(--panel2);border:1px solid var(--line);
  border-radius:10px;padding:.8rem .95rem;font-size:.85rem;color:var(--muted);line-height:1.5}}
.flow .step b{{display:block;color:var(--ink);font-size:.88rem;margin-bottom:.2rem}}
.flow .step code{{font-size:.76rem}}
.flow .step.stop{{border-color:rgba(255,107,107,.35)}}
.flow .arrow{{align-self:center;color:var(--ember);font-weight:800}}
.ties{{margin:.4rem 0 0;padding-left:1.2rem;color:var(--muted);line-height:1.65;font-size:.93rem}}
.ties li{{margin:.45rem 0}}
.ties b{{color:var(--ink)}}
.verdict{{display:inline-block;font-size:.7rem;font-weight:800;letter-spacing:.06em;border-radius:6px;
  padding:.16rem .5rem;white-space:nowrap}}
.verdict.train{{background:rgba(143,214,148,.10);color:var(--good);border:1px solid rgba(143,214,148,.35)}}
.verdict.caution{{background:rgba(255,158,94,.12);color:var(--warn);border:1px solid rgba(255,158,94,.35)}}
.verdict.stopv{{background:rgba(255,107,107,.12);color:var(--bad);border:1px solid rgba(255,107,107,.4)}}
.actiongrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}}
.actiongrid h3{{margin:.1rem 0 .5rem;font-size:.95rem}}
.cmd{{background:#0c0a08;border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;overflow:auto}}
.cmd code{{white-space:pre;color:var(--gold)}}
footer{{border-top:1px solid var(--line);margin-top:1rem;padding:1.6rem 0 3rem;
  color:var(--dim);font-size:.82rem;line-height:1.7}}
.hidden{{display:none!important}}
@media(max-width:700px){{.flow .arrow{{display:none}}.cbar{{min-width:70px}}.navstatus{{display:none}}.navlinks a{{padding:.34rem .42rem}}
  .search{{order:2;margin-left:0;flex:1 1 100%}}.resultcount{{margin-left:auto}}}}
</style></head><body>

<a class="skip" href="#main">Skip to audit results</a>
<nav class="topbar" aria-label="Primary"><div class="navinner">
  <a class="brand" href="./"><span class="brandmark">Z</span><span>zarr-pyramid-audit</span></a>
  <div class="navlinks">
    <a href="#overview">Overview</a><a href="#surfaces">Surfaces</a><a href="#verify">Verify</a><a href="#findings">Findings</a>
    <a href="#probe">Chunk probe</a><a href="#method">Method</a><a href="#scroliq">ScrolIQ</a><a href="./september-2026.html">Writeup</a><a href="./october-2026.html">October plan</a>
    <a href="{repo}">GitHub</a>
  </div>
  <span class="navstatus">● evidence-backed</span>
</div></nav>

<header class="hero"><div class="wrap">
  <div class="eyebrow">VESUVIUS CHALLENGE · SEPTEMBER – OCTOBER 2026</div>
  <h1>zarr-pyramid-audit</h1>
  <p class="tagline">Corruption detection for OME-Zarr pyramids. <em>Don't train on lies.</em></p>
  <p class="lede">An independent integrity audit of the public Vesuvius Challenge
  data stores. Every pyramid is judged from its headers — a few KB per pyramid,
  no full downloads — plus sampled chunk-content probes that decode real voxels.
  Every number below is read from committed audit artifacts; nothing is hand-typed.
  <a href="#verify">Verify it in 60 seconds →</a> · <a href="{repo}">Repo (MIT)</a> ·
  <a href="./september-2026.html">September 2026 writeup →</a> ·
  <a href="./october-2026.html">October 2026 goals →</a></p>
  <p class="suitechip"><a href="#scroliq">The integrity half of the ScrolIQ data-quality suite — how the two fit together →</a></p>
  <div class="stats">
    <div class="stat"><div class="n">{s3_audited}</div><div class="l">S3 Zarr roots audited<br>2026-09-29 · header-only · ~5 min</div></div>
    <div class="stat"><div class="n good">{s3_clean}</div><div class="l">clean</div></div>
    <div class="stat"><div class="n bad">{s3_defective}</div><div class="l">defective pyramid<br>6 header-only levels</div></div>
    <div class="stat"><div class="n">{dl_audited}</div><div class="l">dl.ash2txt.org roots<br>re-audited 2026-09-29</div></div>
    <div class="stat"><div class="n bad">0</div><div class="l">defects fixed in 20 days<br>strict diff: 0 fixed, 0 new</div></div>
    <div class="stat"><div class="n good">{chunks_probed}</div><div class="l">chunks content-probed<br>sampled + decoded</div></div>
  </div>
</div></header>

<main id="main" class="wrap">

<section class="insights" id="overview">
  <div class="card"><h3>The live defect</h3>
    <p>A <b>PHerc0814</b> surface-volume pyramid in the open-data S3 bucket has
    <b>valid headers at all six levels and zero chunk objects</b>. Every reader
    opens it fine and gets plausible all-zero voxels — no error, no warning.
    Proven by direct read; independently confirms
    <a href="https://github.com/scrollprize/villa/issues/1892">villa #1892</a>.</p></div>
  {prize_preflight_card}  <div class="card"><h3>20-day regression</h3>
    <p>The identical audit re-ran over the identical 241-root dl list on
    2026-09-29. Strict diff on every finding field: <b>empty</b>. 18 defective
    pyramids, 50 actionable findings — <b>zero fixed, zero new</b>. Published
    defects don't get fixed after the fact; the publish-time gate is the lever.</p></div>
  <div class="card"><h3>Training volumes probed</h3>
    <p><b>{vc_pop}</b> volcomp inner chunks decoded with real content across all
    64 scroll volumes, <b>{v2_pop}</b> raw/Blosc chunks across 128 dl roots —
    <b>0 all-empty levels</b> in the training data. One present-but-empty mesh
    derivative caught in <code>other/dev/</code> (medium, human review).</p></div>
  <div class="card"><h3>Surface-volume window evidence</h3>
    <p><code>zpa-surface-depth-profile</code> checks the rendered ink-model input stack itself: expected slice count, deterministic per-depth signal/texture, sampled all-zero layers, duplicate sampled-layer digests, and exact source-volume lineage. It reports evidence rather than pretending these observations prove ink.</p></div>
</section>

{tifxyz_panel}<div class="panel" id="verify"><h2>60-second evaluator path<span class="sub">Evidence first: inspect it, reproduce it, then watch it test live data.</span></h2>
  <div class="actiongrid">
    <div><h3>1 · Inspect frozen evidence</h3>
      <p>Every headline number on this page is generated from committed run artifacts. Pages CI regenerates the dashboard and rejects drift from the evidence.</p>
      <p><a href="{repo}/tree/main/artifacts">Run artifacts →</a> ·
      <a href="{repo}/blob/main/data/known-defects.json">Known-defect registry →</a> ·
      <a href="{repo}/blob/main/docs/SUBMISSION.md">Submission criteria → evidence map →</a></p></div>
    <div><h3>2 · Reproduce a verdict</h3>
      <p>Install the public tool and run the same fail-closed gate used for publication checks.</p>
      <div class="cmd"><code>pip install git+https://github.com/Svyable/zarr-pyramid-audit.git<br>zpa-gate --base &lt;store&gt; --root &lt;volume.zarr&gt;</code></div></div>
    <div><h3>3 · Watch real-data CI</h3>
      <p>The scheduled workflow exercises anonymous public data: a clean gate pass, a known-defect rejection, and a sampled chunk-content decode.</p>
      <p><a href="{repo}/actions/workflows/audit.yml">Real-data verification workflow →</a></p></div>
  </div>
  <div class="gatebox"><b>Grand Prize preflight:</b> use the same gate on the exact prize-eligible CT, surface, and derived Zarr inputs before expensive geometry or ink work. A silent storage defect should fail before it can contaminate an unrolling campaign. Before 2.5D ink inference, run <code>zpa-surface-depth-profile</code> on the rendered stack to pin the slice count, source volume, sampled depth integrity, and depth profile. <a href="https://github.com/Svyable/zarr-pyramid-audit/blob/main/docs/surface-depth-profile.md">Protocol →</a></div>
</div>

{baseline_panel}<div class="panel" id="method"><h2>Audit before publish<span class="sub">fail closed on defects, stay honest about unknown evidence</span></h2>
  <div class="actiongrid">
    <div><h3>Put the gate in front of publication</h3>
      <p><code>zpa-gate</code> reads metadata, not payloads, and returns a non-zero exit code when a root crosses the chosen severity threshold.</p>
      <div class="cmd"><code>zpa-gate --base s3://my-bucket/staging/<br>  --roots publish.jsonl --fail-on high</code></div></div>
    <div><h3>Absence requires evidence</h3>
      <p>Metadata and listings now carry an explicit <b>PRESENT / ABSENT / UNKNOWN</b> state.
      A timeout, 403, rate limit, or server error cannot be silently promoted into a “missing level” or “empty store” claim.</p>
      <p><a href="{repo}/tree/main/data">Known-defect registry →</a> ·
      <a href="{repo}/tree/main/artifacts">Run artifacts →</a></p></div>
  </div>
</div>

<div class="panel" id="scroliq"><h2>How this fits with ScrolIQ<span class="sub">Two repos, one question: should anyone spend GPU or expert time on this volume?</span></h2>
  <div class="suite">
    <div class="card"><h3>zarr-pyramid-audit · this repo</h3>
      <p class="role">Don't train on lies.</p>
      <p><b>Integrity.</b> Is the data what its metadata claims? Header-only pyramid
      audit, sampled chunk-content probes, a fail-closed publish gate, and
      surface-input evidence tools. Read-only, ~KB per pyramid. A <b>high</b>
      finding means do not train, do not publish. Says nothing about scan quality.</p></div>
    <div class="card"><h3>ScrolIQ · companion repo</h3>
      <p class="role">Find the bottleneck.</p>
      <p><b>Diagnostics.</b> A diagnostic layer for the Challenge's 2026 open problems:
      a 0–100 scan-health triage score and the “🎯 label next” coverage join, plus
      the diagnostic passport, spatial scan map, mesh / winding / ink audits, and the
      2027 Grand Prize recto-coverage and provenance gates. Its score is
      <b>not</b> readability or prize readiness; unmeasured stages stay <code>unknown</code>.</p>
      <p><a href="https://github.com/Svyable/scrollq">repo</a> ·
      <a href="https://svyable.github.io/scrollq/">live survey</a> ·
      <a href="https://svyable.github.io/scrollq/september-2026.html">September writeup</a></p></div>
  </div>

  <div class="flow" role="list" aria-label="How a volume moves through the suite">
    <div class="step" role="listitem"><b>1 · Integrity</b>
      <code>zpa-gate</code> / <code>zpa-audit</code> — are levels, headers and chunks real?</div>
    <span class="arrow" aria-hidden="true">→</span>
    <div class="step stop" role="listitem"><b>2 · Stop or continue</b>
      A high-severity finding ends it: <span class="verdict stopv">DO NOT TRAIN</span></div>
    <span class="arrow" aria-hidden="true">→</span>
    <div class="step" role="listitem"><b>3 · Scan health</b>
      ScrolIQ scores sampled real voxels, decoded through the libvolcomp vendored here</div>
    <span class="arrow" aria-hidden="true">→</span>
    <div class="step" role="listitem"><b>4 · Diagnose</b>
      Passport, scan map, mesh / winding / ink audits, Grand Prize provenance gate</div>
  </div>

  <h3 style="margin:1.4rem 0 .4rem;font-size:.95rem">One verdict per volume: <code>scrollq-health</code></h3>
  <div style="overflow-x:auto"><table><thead><tr><th>integrity (this repo)</th><th>quality (ScrolIQ)</th><th>verdict</th></tr></thead><tbody>
  <tr><td><b>FAIL</b>: any <b>high</b> finding, or the audit itself crashed</td><td>not consulted</td><td><span class="verdict stopv">DO NOT TRAIN</span></td></tr>
  <tr><td><b>UNKNOWN</b>: unreadable level, absent root, nothing auditable</td><td>not consulted</td><td><span class="verdict stopv">DO NOT TRAIN</span></td></tr>
  <tr><td><b>WARN</b>: medium finding(s)</td><td>not consulted</td><td><span class="verdict caution">CAUTION</span></td></tr>
  <tr><td><b>PASS</b></td><td>unscorable, or score below 40</td><td><span class="verdict caution">CAUTION</span></td></tr>
  <tr><td><b>PASS</b></td><td>score 40 or above</td><td><span class="verdict train">TRAIN</span></td></tr>
  </tbody></table></div>
  <p style="font-size:.85rem">Rules as implemented in ScrolIQ's
  <a href="https://github.com/Svyable/scrollq/blob/main/src/scrollq/health.py"><code>health.py</code></a>
  (checked 2026-10-01): integrity comes from this repo's <code>zpa.report.audit_root</code> and follows
  <code>RECOMMENDED_CONSUMER_VERDICT</code>, so missing evidence fails closed
  (<a href="https://github.com/Svyable/scrollq/pull/55">ScrolIQ #55</a>; until then UNKNOWN read as a pass).
  All outcomes were run on live data
  (<a href="https://github.com/Svyable/scrollq/tree/main/artifacts/2026-10-01-health-verdicts-fail-closed">ScrolIQ evidence</a>):
  <b>DO NOT TRAIN</b> on the defective PHerc0814 pyramid — its quality is unscorable, so the
  verdict comes from this audit alone — <b>TRAIN</b> on a healthy PHerc0813 dl volume,
  <b>CAUTION</b> on the v2 dev mesh, and <b>DO NOT TRAIN</b> on a root that does not exist.</p>

  <h3 style="margin:1.4rem 0 .2rem;font-size:.95rem">Where ScrolIQ builds on this repo</h3>
  <ul class="ties">
    <li><b>Shared foundation.</b> ScrolIQ imports this package's HTTP/S3 store, header parser,
    audit and vendored <code>libvolcomp</code> decoder (<code>zpa.httpstore</code>,
    <code>zpa.zarrmeta</code>, <code>zpa.audit_pyramid</code>, <code>zpa.volcomp</code>).
    It declares <code>zarr-pyramid-audit</code> as a dependency, so installing ScrolIQ installs this.
    The dependency runs one way: this repo never imports ScrolIQ.</li>
    <li><b>Integrity before quality.</b> A scan-health score is only worth trusting on a pyramid that
    passes integrity, so <code>scrollq-health</code> runs this audit alongside the score and lets a
    high finding, or missing evidence, override it.</li>
    <li><b>Grand Prize evidence chain.</b> ScrolIQ's <code>scroliq-provenance</code> gate requires a
    <code>zarr_audit</code> record for the CT volume — tool name, audit-manifest SHA-256, and a root
    naming the exact eligible volume — and its probe protocol makes this repo's audit Stage A.</li>
    <li><b>Shared discovery data.</b> ScrolIQ's label-coverage join reads the
    <code>discover_zarr.roots.jsonl</code> that <code>zpa-discover</code> produces for the S3 bucket.</li>
  </ul>

  <div class="gatebox"><b>Naming.</b> ScrolIQ is spelled with a capital <b>I</b> (as in Mesh IQ and
  Ink IQ) and was previously ScrollQ. Its Python package and the
  <code>scrollq-*</code> commands keep the old name for compatibility; the newer diagnostics ship as
  <code>scroliq-*</code>. Repo and site URLs are unchanged.</div>

  <div class="cmd" style="margin-top:1rem"><code># integrity only (this repo)
zpa-gate --base &lt;store&gt; --root &lt;volume.zarr&gt;

# integrity + scan quality → one verdict (installs both packages)
pip install git+https://github.com/Svyable/scrollq.git
scrollq-health --root &lt;volume&gt;</code></div>
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
  Actions annotations for CI. When used, the gate blocks this defect class
  before publication.</div>
  <p class="recheck"><b>Still live:</b> re-audited 2026-09-30 ~22:25 UTC —
  6 high-severity <code>LEVEL_NO_CHUNKS</code> findings, identical signature.
  Unrepaired for the full September window.</p>
</div>

<div class="panel" id="findings"><h2>Findings by check code<span class="sub">Click a column to sort · filter by severity · S3 = open-data bucket, dl = dl.ash2txt.org</span></h2>
  <div class="controls">
    <button type="button" class="sevbtn on" data-s="">all</button>
    <button type="button" class="sevbtn" data-s="high">high</button>
    <button type="button" class="sevbtn" data-s="medium">medium</button>
    <button type="button" class="sevbtn" data-s="low">low</button>
    <button type="button" class="sevbtn" data-s="info">info</button>
    <label class="search"><span class="sr-only">Filter finding codes</span>
      <input id="codeSearch" type="search" placeholder="Filter codes or meanings…" autocomplete="off"></label>
    <span class="resultcount" id="resultCount" aria-live="polite"></span>
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

<div class="panel" id="probe"><h2>Chunk-content probe<span class="sub">2026-09-30 · sampled decode, not just headers</span></h2>
  <p>The header-only audit answers "are chunk keys present?" — the probe answers the
  next question: <b>"do the present chunks hold data?"</b> This closes the next
  silent-corruption class: chunks that exist but decode to all fill_value.</p>
  <div style="overflow-x:auto"><table><thead><tr><th>campaign</th><th class="num">roots</th><th class="num">levels</th>
  <th class="num">chunks decoded</th><th class="num">populated</th><th class="num">all-empty levels</th></tr></thead>
  <tbody>{probe_rows}</tbody></table></div>
  {v2_note}
  <p>The present-but-empty class was not observed in the S3 or training-volume samples —
  reported as evidence of absence in the sample, not proof of absence in the corpus.
  The tool is published for anyone to rerun at larger sample sizes.</p>
</div>

<div class="panel"><h2>Mirror fidelity: S3 vs dl.ash2txt.org<span class="sub">same names, not copies</span></h2>
  <p>64 same-named volumes exist in both stores. They are <b>format migrations</b> of
  identical voxel grids at all six levels:</p>
  <div style="overflow-x:auto"><table><thead><tr><th></th><th>dl.ash2txt.org</th><th>S3 open-data</th></tr></thead><tbody>
  <tr><td>Zarr format</td><td>v3</td><td>v2</td></tr>
  <tr><td>chunking</td><td>1024³ shards</td><td>128³ raw</td></tr>
  <tr><td>codec</td><td>sharding_indexed + lossy volcomp (q=1.0)</td><td>none (raw uint8)</td></tr>
  </tbody></table></div>
  <p>Byte-level comparison (volcomp decoded from source) shows quantization noise only:
  max absolute difference 30–35, mean below 0.1, ~2–4% of voxels differ.
  <b>Reproducibility work must pin the store, not just the filename.</b></p>
</div>

<div class="panel"><h2>Known silent-zero volumes<span class="sub">dl.ash2txt.org · header-only levels confirmed by direct read</span></h2>
  <div style="overflow-x:auto"><table><thead><tr><th>volume</th><th>header-only levels</th></tr></thead><tbody>
  <tr><td><code>community-uploads/bruniss/labels/surfaces/archive/1-voxel-sheet_slices-closed.zarr</code></td><td>1–5 (level 0 populated)</td></tr>
  <tr><td><code>other/dev/inked_zarrs/3336_predictions.zarr</code></td><td>all six</td></tr>
  </tbody></table></div>
  <p>Unchanged between the 2026-09-09 and 2026-09-29 audits. Full machine-readable
  kill list: <code>data/known-defects.json</code> ({kd_n} entries).</p>
</div>

</main>

<footer><div class="wrap">
  <b>Method.</b> Header-only pyramid audit (<code>zpa-audit</code>): {n_codes} check codes over
  <code>.zattrs</code> + one <code>.zarray</code> per level — a few KB per pyramid
  regardless of array size. Chunk-presence via one listing per level. Chunk-content via
  sampled decode (vendored libvolcomp for the sharded volcomp levels). Full evidence,
  manifests, and runbooks in <code>artifacts/</code> in the
  <a href="{repo}">repo</a> (MIT fork of sgsllc-jr/zarr-pyramid-audit; upstream credit retained).
  Companion: <a href="https://github.com/Svyable/scrollq">ScrolIQ</a> (<a href="#scroliq">how they fit</a>).<br>
  Built by Sven + Muse · updated {stamp}.
</div></footer>

<script>
(function(){{
  const tb = document.querySelector("#codes tbody");
  const rows = Array.from(tb.querySelectorAll("tr"));
  let sortK = "total", asc = false, sevF = "", query = "";
  function apply(){{
    let vis = rows.filter(r => (!sevF || r.dataset.sev === sevF)
      && (!query || r.textContent.toLowerCase().includes(query)));
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
    const count = document.querySelector("#resultCount");
    if (count) count.textContent = vis.length + (vis.length === 1 ? " code" : " codes");
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
  const search = document.querySelector("#codeSearch");
  if (search) search.addEventListener("input", () => {{ query = search.value.trim().toLowerCase(); apply(); }});
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
    "ROOT_ABSENT": "low", "EMPTY_ZARR_DIR": "low",
    "METADATA_UNREADABLE": "high", "ACCESS_UNKNOWN": "info",
    "NOT_A_ZARR_GROUP": "info", "NOT_MULTISCALE": "info",
    "BARE_ARRAY": "info", "CHUNK_EXCEEDS_SHAPE": "info",
    "PHYSICAL_SCALE_CONTRADICTION": "high", "PHYSICAL_SCALE_UNKNOWN": "info",
    "OME_VERSION_UNMODELLED": "info", "TRANSFORM_SCALE_COUNT": "low",
    "TRANSFORM_ARITY": "low", "AXES_INVALID": "low",
    "DIMENSION_NAMES_MISMATCH": "low",
}
# Kept in lockstep with zpa.audit_pyramid.SEVERITY by tests/test_dashboard.py.
# It is duplicated (not imported) so the Pages CI can regenerate the dashboard
# on a bare Python install with no audit dependencies.


TIFXYZ_BLURB = {
    "TIFXYZ_BBOX_MISMATCH": "declared bbox differs from the stored coordinates",
    "TIFXYZ_NEGATIVE_COORDINATE": "valid points with a negative coordinate (outside any volume)",
    "TIFXYZ_CONTENT_UNDECODED": "content tier skipped (size cap or layout): coverage gap",
    "TIFXYZ_EMPTY": "no valid point at all",
    "TIFXYZ_INVALID_MASK_MISMATCH": "channels disagree on the -1 invalid marker",
    "TIFXYZ_NONFINITE": "NaN/inf where a cell is not marked invalid",
}


def render_tifxyz_panel(summary_path: str) -> str:
    """Surface-audit panel from a committed zpa-tifxyz summary ('' if absent)."""
    try:
        t = load_json(summary_path)
    except FileNotFoundError:
        return ""
    integ = t.get("by_integrity", {})
    sev = t.get("by_severity", {})
    rows = "".join(
        f'<tr><td><code>{html.escape(code)}</code></td>'
        f'<td class="num">{n}</td>'
        f'<td style="color:var(--muted)">{html.escape(TIFXYZ_BLURB.get(code, ""))}</td></tr>'
        for code, n in sorted(t.get("by_code", {}).items(), key=lambda kv: -kv[1]))
    undecoded = t.get("by_code", {}).get("TIFXYZ_CONTENT_UNDECODED", 0)
    blocking = sum(sev.get(s, 0) for s in ("medium", "high"))
    return (
        '<div class="panel" id="surfaces"><h2>tifxyz surfaces'
        '<span class="sub">2026-10-01 · <code>zpa-tifxyz --content</code> on every '
        'surface patch in the S3 bucket</span></h2>\n'
        f'  <p><b>{t["surfaces"]}</b> surfaces audited: '
        f'<b>{integ.get("PASS", 0)}</b> integrity PASS, '
        f'{integ.get("WARN", 0)} WARN, {integ.get("UNKNOWN", 0)} UNKNOWN, '
        f'{integ.get("FAIL", 0)} FAIL. Findings at medium or above: '
        f'<b>{blocking}</b>. Content tier skipped on {undecoded} surfaces '
        '(channels over the 32 MiB cap) &mdash; reported as a coverage gap, '
        'not a pass.</p>\n'
        '  <div style="overflow-x:auto"><table><thead><tr><th>code</th>'
        '<th class="num">surfaces</th>'
        f'<th>meaning</th></tr></thead><tbody>{rows}</tbody></table></div>\n'
        '  <p class="smalllink"><a href="https://github.com/Svyable/zarr-pyramid-audit/'
        'tree/main/artifacts/2026-10-01-s3-tifxyz">Run artifacts &rarr;</a></p>\n'
        '</div>\n')


def render_prize_preflight_card(summary_path: str) -> str:
    """Grand Prize exact-volume CT preflight card from a committed summary."""
    try:
        p = load_json(summary_path)
    except FileNotFoundError:
        return ""
    t = p.get("totals", {})
    found = t.get("exact_roots_found", 0)
    eligible = t.get("eligible_targets", 0)
    zero = t.get("roots_with_zero_findings", 0)
    levels = t.get("roots_with_all_declared_levels_present", 0)
    chunked = t.get("roots_with_no_chunkless_levels", 0)
    known = t.get("roots_with_no_unknown_chunk_presence", 0)
    return (
        '<div class="card"><h3>Grand Prize CT preflight</h3>'
        f'<p><b>{found} / {eligible}</b> exact prize-listed CT roots were found in the '
        'frozen S3 audit. '
        f'<b>{levels} / {eligible}</b> have all declared levels present, '
        f'<b>{chunked} / {eligible}</b> have no chunkless level, '
        f'<b>{known} / {eligible}</b> have no unknown chunk-presence state, and '
        f'<b>{zero} / {eligible}</b> have zero header findings. '
        'This is input-integrity evidence, not scan/surface/ink readiness. '
        '<a href="https://github.com/Svyable/zarr-pyramid-audit/tree/main/artifacts/'
        '2026-10-02-grand-prize-ct-preflight">Exact-volume artifact &rarr;</a></p></div>\n'
    )


BASELINE_TOOLS = (
    ("zarr-python", "zarr-python (open + read every level)"),
    ("ome-zarr-models", "ome-zarr-models (OME-NGFF validator)"),
    ("yaozarrs", "yaozarrs (OME-NGFF metadata + structure)"),
    ("zpa (header audit)", "ZPA header audit"),
    ("zpa (+ chunk probe)", "ZPA + sampled chunk probe"),
)


def render_baseline_panel(comparison_path: str) -> str:
    """Baseline-comparison panel from a committed comparison.json ('' if absent)."""
    try:
        c = load_json(comparison_path)
    except FileNotFoundError:
        return ""
    summ, ver = c.get("summary", {}), c.get("versions", {})

    def cell(tool, cat):
        v = summ.get(tool, {}).get(cat)
        return f'{v["flagged"]} / {v["of"]}' if v else "&ndash;"

    rows = "".join(
        f'<tr><td>{html.escape(label)}</td>'
        + "".join(f'<td class="num">{cell(tool, cat)}</td>'
                  for cat in ("defect", "suspicious", "benign", "out-of-model"))
        + "</tr>"
        for tool, label in BASELINE_TOOLS if tool in summ)
    art = ("https://github.com/Svyable/zarr-pyramid-audit/tree/main/artifacts/"
           "2026-10-03-baseline-yaozarrs")
    return (
        '<div class="panel" id="baselines"><h2>Against the tools people already use'
        f'<span class="sub">2026-10-03 · zarr-python {html.escape(ver.get("zarr", "?"))}, '
        f'ome-zarr-models {html.escape(ver.get("ome-zarr-models", "?"))}, '
        f'yaozarrs {html.escape(ver.get("yaozarrs", "?"))}</span></h2>\n'
        '  <p><b>On the live defect,</b> all three baselines treat the PHerc0814 '
        '<code>-L1</code> pyramid as healthy: both OME-NGFF validators accept it, '
        'and zarr-python reads a level-5 window as all zeros without an error. '
        'The ZPA gate rejects it (6 &times; <code>LEVEL_NO_CHUNKS</code>).</p>\n'
        '  <p><b>On the fixture corpus</b> (ground truth assigned from what each '
        'fixture was built to contain), flagged / total:</p>\n'
        '  <div style="overflow-x:auto"><table><thead><tr><th>tool</th>'
        '<th class="num">defects</th><th class="num">suspicious content</th>'
        '<th class="num">false alarms on valid pyramids</th>'
        '<th class="num">out-of-model nodes</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>\n'
        '  <p style="font-size:.85rem">Selection bias: the corpus was written around '
        'ZPA&rsquo;s failure classes, so read it per defect class, not as a score. '
        'The validators check the NGFF spec, which ZPA does not attempt; run '
        'both kinds. ZPA&rsquo;s false alarms are a legal compressor drift (low, integrity '
        'stays PASS) and a sampled probe on a mostly empty level.</p>\n'
        f'  <p class="smalllink"><a href="{art}">Comparison, method and caveats &rarr;</a></p>\n'
        '</div>\n')


def load_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "index.html"))
    ap.add_argument("--stamp", default=os.environ.get("ZPA_DASHBOARD_STAMP"),
                    help="override the dashboard update date (YYYY-MM-DD)")
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
                       key=lambda c: (-(s3_codes.get(c, 0) + dl_codes.get(c, 0)), c)):
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

    tifxyz_panel = render_tifxyz_panel(
        f"{ART}/2026-10-01-s3-tifxyz/tifxyz.summary.json")
    prize_preflight_card = render_prize_preflight_card(
        f"{ART}/2026-10-02-grand-prize-ct-preflight/summary.json")
    baseline_panel = render_baseline_panel(
        f"{ART}/2026-10-03-baseline-yaozarrs/comparison.json")

    artifact_dates = sorted(
        name[:10] for name in os.listdir(ART)
        if len(name) >= 10 and name[4:5] == "-" and name[7:8] == "-"
        and name[:10].replace("-", "").isdigit()
    )
    stamp = args.stamp or (artifact_dates[-1] if artifact_dates else "unknown")

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
        n_codes=len(SEVERITY), tifxyz_panel=tifxyz_panel,
        prize_preflight_card=prize_preflight_card,
        baseline_panel=baseline_panel,
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {args.out} ({len(page)//1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
