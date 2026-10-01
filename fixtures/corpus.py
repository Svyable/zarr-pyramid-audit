"""
corpus.py -- the zarr-pyramid-audit fixture corpus: definitions, builder,
runner and golden projection.

Each case isolates ONE property. Three kinds:

  * ``zarr/<case>.zarr``   tiny on-disk Zarr trees, built deterministically
                           by ``build()`` below and committed.
  * ``http/<case>.json``   recorded HTTP responses (status + body per path)
                           replayed through the real ``HttpStore`` -- the
                           transport failures a directory tree cannot show.
  * ``http/range-cases.json``  byte-range / suffix-range responses, including
                           ambiguous and invalid ones, with the expected
                           result or error of ``get_range``/``get_suffix``.

``expected/<case>.json`` holds the golden structured output for every Zarr
and HTTP case: per-finding code/severity/level/evidence state, per-level
evidence, the report's integrity and coverage, the gate verdict, the
recommended consumer verdict and (for on-disk cases) the sampled chunk
probe. It is a projection of the full report that leaves out free-text
detail strings and environment-specific values (paths, tool version).

Regenerate after an intentional change, then review the diff:

    python fixtures/corpus.py build            # rewrite zarr/ trees
    python fixtures/corpus.py expected         # rewrite expected/*.json + README table
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ZARR_DIR = os.path.join(HERE, "zarr")
SURF_DIR = os.path.join(HERE, "surfaces")
HTTP_DIR = os.path.join(HERE, "http")
EXPECTED_DIR = os.path.join(HERE, "expected")

CORPUS_VERSION = "1"

# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

AXES3 = [{"name": n, "type": "space"} for n in ("z", "y", "x")]


def _dump(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _raw(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _text(path: str, text: str) -> None:
    _raw(path, text.encode("utf-8"))


def _grid(shape, chunks):
    return [max(1, math.ceil(s / c)) for s, c in zip(shape, chunks)]


def _indices(grid):
    if not grid:
        yield ()
        return
    for i in range(grid[0]):
        for rest in _indices(grid[1:]):
            yield (i,) + rest


def _pattern(n: int, seed: int) -> bytes:
    """Deterministic, never-zero payload."""
    return bytes(((i * 7 + seed) % 251) + 1 for i in range(n))


def _itemsize(dtype: str) -> int:
    return int("".join(c for c in dtype if c.isdigit()) or 1)


def v2_array(path, shape, chunks, *, dtype="|u1", fill_value=0,
             compressor=None, separator=".", payload="data",
             only=None, seed=0):
    """Write a zarr v2 array header plus chunks.

    payload: "data" (nonzero pattern), "zeros", "const:<byte>", "nan"
    (float NaN), "none" (header only). ``only`` restricts which chunk indices are written.
    """
    header = {"zarr_format": 2, "shape": list(shape), "chunks": list(chunks),
              "dtype": dtype, "fill_value": fill_value,
              "compressor": compressor, "filters": None, "order": "C"}
    if separator != ".":
        header["dimension_separator"] = separator
    _dump(os.path.join(path, ".zarray"), header)
    if payload == "none" or any(s <= 0 for s in shape):
        return
    nbytes = _itemsize(dtype)
    for c in chunks:
        nbytes *= c
    for n, idx in enumerate(_indices(_grid(shape, chunks))):
        if only is not None and idx not in only:
            continue
        if payload == "zeros":
            data = bytes(nbytes)
        elif payload.startswith("const:"):
            data = bytes([int(payload[6:])]) * nbytes
        elif payload == "nan":
            import struct
            data = struct.pack("<f", float("nan")) * (nbytes // 4)
        else:
            data = _pattern(nbytes, seed + n)
        if compressor and compressor.get("id") == "blosc":
            from numcodecs import Blosc
            data = Blosc(cname=compressor["cname"], clevel=compressor["clevel"],
                         shuffle=compressor["shuffle"]).encode(data)
        key = separator.join(map(str, idx))
        _raw(os.path.join(path, *key.split("/")), data)


def v2_group(path, datasets, *, axes=AXES3, extra_ms=None, attrs=None):
    _dump(os.path.join(path, ".zgroup"), {"zarr_format": 2})
    if attrs is None:
        ms = {"version": "0.4", "axes": axes, "datasets": [
            {"path": p, "coordinateTransformations": [
                {"type": "scale", "scale": list(s)}]} for p, s in datasets]}
        if extra_ms:
            ms.update(extra_ms)
        attrs = {"multiscales": [ms]}
    _dump(os.path.join(path, ".zattrs"), attrs)


def pyramid(path, levels, **group_kw):
    """levels: list of (path, scale, shape, chunks, array_kwargs)."""
    v2_group(path, [(p, s) for p, s, *_ in levels], **group_kw)
    for p, _s, shape, chunks, kw in levels:
        if kw is None:
            continue  # declared but not written
        v2_array(os.path.join(path, p), shape, chunks, **kw)


S1, S2, S4 = [1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [4.0, 4.0, 4.0]
C = [4, 8, 8]


def _clean_levels(**overrides):
    lv = [["0", S1, [8, 16, 16], C, {}],
          ["1", S2, [4, 8, 8], C, {"seed": 1}],
          ["2", S4, [2, 4, 4], [2, 4, 4], {"seed": 2}]]
    for idx, kw in overrides.items():
        lv[int(idx)][4] = {**lv[int(idx)][4], **kw} if kw is not None else None
    return [tuple(x) for x in lv]


BLOSC = {"id": "blosc", "cname": "lz4", "clevel": 5, "shuffle": 1,
         "blocksize": 0}


def build_v3_clean(path, dimension_names=True):
    _dump(os.path.join(path, "zarr.json"), {
        "zarr_format": 3, "node_type": "group",
        "attributes": {"ome": {"version": "0.5", "multiscales": [{
            "axes": AXES3,
            "datasets": [
                {"path": "0", "coordinateTransformations": [
                    {"type": "scale", "scale": S1}]},
                {"path": "1", "coordinateTransformations": [
                    {"type": "scale", "scale": S2}]}]}]}}})
    for p, shape, seed in (("0", [8, 16, 16], 0), ("1", [4, 8, 8], 1)):
        _dump(os.path.join(path, p, "zarr.json"), {
            "zarr_format": 3, "node_type": "array", "shape": shape,
            "data_type": "uint8",
            "chunk_grid": {"name": "regular",
                           "configuration": {"chunk_shape": C}},
            "chunk_key_encoding": {"name": "default",
                                   "configuration": {"separator": "/"}},
            "fill_value": 0, "codecs": [{"name": "bytes"}],
            **({"dimension_names": ["z", "y", "x"]} if dimension_names else {}),
            "attributes": {}})
        for n, idx in enumerate(_indices(_grid(shape, C))):
            _raw(os.path.join(path, p, "c", *map(str, idx)),
                 _pattern(4 * 8 * 8, seed * 100 + n))


def _phys(marker, *, units=False, base=S1):
    axes = [dict(a) for a in AXES3]
    if units:
        for a in axes:
            a["unit"] = "micrometer"
    b = list(base)
    return dict(
        levels=[("0", b, [8, 16, 16], C, {}),
                ("1", [x * 2 for x in b], [4, 8, 8], C, {"seed": 1})],
        axes=axes, extra_ms={"metadata": {"physical_size": marker}})


def _with_datasets(path, mutate):
    """Build the clean pyramid, then edit its multiscales datasets in place."""
    pyramid(path, _clean_levels())
    zattrs = os.path.join(path, ".zattrs")
    with open(zattrs, encoding="utf-8") as fh:
        attrs = json.load(fh)
    mutate(attrs["multiscales"][0])
    _dump(zattrs, attrs)


def _two_scales_on_level_1(ms):
    ms["datasets"][1]["coordinateTransformations"].append(
        {"type": "scale", "scale": S2})


def _short_translation_on_level_1(ms):
    ms["datasets"][1]["coordinateTransformations"].append(
        {"type": "translation", "translation": [0.5, 0.5]})


def _duplicate_axis_name(ms):
    ms["axes"] = [{"name": "z", "type": "space"}, {"name": "y", "type": "space"},
                  {"name": "y", "type": "space"}]


def _build_pyramid_case(path, spec):
    levels = spec.pop("levels")
    pyramid(path, levels, **spec)


# Each case: (name, property, builder(path)). The builder writes the tree.
ZARR_CASES = [
    ("clean_v2", "clean 3-level v2 pyramid; no findings at any severity",
     lambda p: pyramid(p, _clean_levels())),
    ("clean_v3", "clean 2-level zarr v3 / OME 0.5 pyramid with raw 'bytes' chunks",
     build_v3_clean),
    ("missing_level", "level 2 declared in multiscales, no header on disk",
     lambda p: pyramid(p, _clean_levels(**{"2": None}))),
    ("level_no_chunks", "level 1 header present, zero chunk keys (silent fill_value)",
     lambda p: pyramid(p, _clean_levels(**{"1": {"payload": "none"}}))),
    ("level_undeclared", "level directory 3 exists with a header but is not declared",
     lambda p: (pyramid(p, _clean_levels()),
                v2_array(os.path.join(p, "3"), [1, 2, 2], [1, 2, 2], seed=3))),
    ("scale_shape_mismatch", "level 1 shape matches neither ceil nor floor of base/2",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C, {}),
                           ("1", S2, [4, 8, 7], C, {"seed": 1})])),
    ("mixed_rounding", "level 1 rounds up (ceil), level 2 rounds down (floor)",
     lambda p: pyramid(p, [("0", S1, [9, 17, 17], C, {}),
                           ("1", S2, [5, 9, 9], C, {"seed": 1}),
                           ("2", S4, [2, 4, 4], [2, 4, 4], {"seed": 2})])),
    ("scale_nonmonotonic", "declared scale does not increase from level 1 to level 2",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C, {}),
                           ("1", S2, [4, 8, 8], C, {"seed": 1}),
                           ("2", S2, [4, 8, 8], C, {"seed": 2})])),
    ("dtype_drift", "level 1 is uint16 while level 0 is uint8",
     lambda p: pyramid(p, _clean_levels(**{"1": {"dtype": "<u2"}}))),
    ("fill_drift", "level 1 fill_value differs from level 0",
     lambda p: pyramid(p, _clean_levels(**{"1": {"fill_value": 255}}))),
    ("compressor_drift", "level 1 is blosc-compressed, levels 0 and 2 are raw",
     lambda p: pyramid(p, _clean_levels(**{"1": {"compressor": BLOSC}}))),
    ("separator_drift", "level 1 uses '/' dimension_separator, others '.'",
     lambda p: pyramid(p, _clean_levels(**{"1": {"separator": "/"}}))),
    ("ndim_drift", "level 1 is 2-D inside a 3-D pyramid",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C, {}),
                           ("1", S2, [8, 8], [8, 8], {"seed": 1})])),
    ("axes_mismatch", "two axes declared for 3-D arrays",
     lambda p: pyramid(p, _clean_levels(), axes=AXES3[1:])),
    ("degenerate_level", "level 1 has a zero extent",
     lambda p: pyramid(p, _clean_levels(**{"1": {}})[:1]
                       + [("1", S2, [0, 8, 8], C, {"seed": 1})])),
    ("chunk_exceeds_shape", "deepest level chunk exceeds its shape on every axis (benign info)",
     lambda p: pyramid(p, _clean_levels()[:2]
                       + [("2", S4, [2, 4, 4], C, {"seed": 2})])),
    ("physical_scale_unknown", "physical_size explicitly 'unknown', no contradicting claim (info)",
     lambda p: _build_pyramid_case(p, _phys("unknown"))),
    ("physical_scale_contradiction_units",
     "physical_size 'unknown' but spatial axes declare micrometer units",
     lambda p: _build_pyramid_case(p, _phys("unknown", units=True))),
    ("physical_scale_contradiction_scale",
     "physical_size 'unknown' but level-0 spatial scale is not identity",
     lambda p: _build_pyramid_case(p, _phys("unknown", base=[2.0, 2.0, 2.0]))),
    ("physical_scale_unspecified",
     "no physical_size marker plus units and a real voxel size: nothing is guessed",
     lambda p: pyramid(
         p, [("0", [7.91] * 3, [8, 16, 16], C, {}),
             ("1", [15.82] * 3, [4, 8, 8], C, {"seed": 1})],
         axes=[{**a, "unit": "micrometer"} for a in AXES3])),
    ("ome_version_unmodelled",
     "declares OME-NGFF 0.6, newer than the audit models: conformance checks skipped (info)",
     lambda p: pyramid(p, _clean_levels(), extra_ms={"version": "0.6"})),
    ("transform_scale_count", "level 1 declares two scale transforms (spec: exactly one)",
     lambda p: _with_datasets(p, _two_scales_on_level_1)),
    ("transform_arity", "level 1 translation has 2 entries for 3 axes",
     lambda p: _with_datasets(p, _short_translation_on_level_1)),
    ("dimension_names_missing",
     "OME-Zarr 0.5 v3 pyramid whose arrays have no dimension_names",
     lambda p: build_v3_clean(p, dimension_names=False)),
    ("axes_invalid", "two axes share the name 'y'",
     lambda p: _with_datasets(p, _duplicate_axis_name)),
    ("multiscale_empty", "multiscales key present with an empty datasets list",
     lambda p: v2_group(p, [], attrs={"multiscales": [{"version": "0.4",
                                                       "datasets": []}]})),
    ("not_multiscale", "valid Zarr group that never claims to be a pyramid (info)",
     lambda p: v2_group(p, [], attrs={"description": "component arrays"})),
    ("bare_array", "single-scale v2 array at the root (info)",
     lambda p: v2_array(p, [4, 8, 8], C)),
    ("headerless_chunk_store", "chunk keys present, no .zarray/.zgroup/zarr.json",
     lambda p: (_raw(os.path.join(p, "0.0.0"), _pattern(256, 0)),
                _raw(os.path.join(p, "0.0.1"), _pattern(256, 1)))),
    ("container_no_group_header", "children are Zarr arrays; no group header at root",
     lambda p: (v2_array(os.path.join(p, "a"), [4, 8, 8], C),
                v2_array(os.path.join(p, "b"), [4, 8, 8], C, seed=5))),
    ("not_a_zarr_group", "directory named *.zarr with nothing Zarr-like inside (info)",
     lambda p: _text(os.path.join(p, "README.txt"), "not a zarr store\n")),
    ("root_absent", "requested root does not exist (confirmed absence)",
     lambda p: None),
    ("malformed_zgroup", "truncated .zgroup JSON",
     lambda p: _text(os.path.join(p, ".zgroup"), '{"zarr_format": 2')),
    ("malformed_zattrs", "valid .zgroup, truncated .zattrs JSON",
     lambda p: (_dump(os.path.join(p, ".zgroup"), {"zarr_format": 2}),
                _text(os.path.join(p, ".zattrs"), '{"multiscales": [{"datasets": ['))),
    ("malformed_level_header", "level 1 .zarray is truncated JSON",
     lambda p: (pyramid(p, _clean_levels(**{"1": None})),
                _text(os.path.join(p, "1", ".zarray"), '{"zarr_format": 2, "shape": [4,'),
                _raw(os.path.join(p, "1", "0.0.0"), _pattern(256, 9)))),
    # ---- chunk-content cases: header audit is clean, the probe is not ----
    ("present_all_fill", "every chunk is stored but decodes to fill_value 0",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C, {"payload": "zeros"}),
                           ("1", S2, [4, 8, 8], C, {"payload": "zeros"})])),
    ("zero_data_nonzero_fill",
     "chunks hold zeros but fill_value is 255: zero-filled is data, not empty",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C,
                            {"payload": "zeros", "fill_value": 255}),
                           ("1", S2, [4, 8, 8], C,
                            {"payload": "zeros", "fill_value": 255})])),
    ("nan_fill_all_empty", "float32 chunks all NaN with fill_value \"NaN\" (v2 string form)",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C,
                            {"dtype": "<f4", "fill_value": "NaN", "payload": "nan"}),
                           ("1", S2, [4, 8, 8], C,
                            {"dtype": "<f4", "fill_value": "NaN", "payload": "nan"})])),
    ("sparse_level", "only 3 of 8 level-0 chunks stored: missing is not empty",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C,
                            {"only": {(0, 0, 0), (0, 1, 0), (1, 1, 1)}}),
                           ("1", S2, [4, 8, 8], C, {"seed": 1})])),
    ("all_fill_nonzero", "every stored byte equals fill_value 255: empty, though no byte is zero",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C,
                            {"payload": "const:255", "fill_value": 255}),
                           ("1", S2, [4, 8, 8], C,
                            {"payload": "const:255", "fill_value": 255})])),
    ("sparse_unsampled",
     "one stored chunk in a 64-chunk level, outside every spread sample: a coverage gap",
     lambda p: pyramid(p, [("0", S1, [16, 32, 32], C, {"only": {(0, 0, 1)}}),
                           ("1", S2, [8, 16, 16], C, {"seed": 1})])),
    ("undecodable_codec", "chunks use a codec the probe cannot decode (zstd): reported, never guessed",
     lambda p: pyramid(p, [("0", S1, [8, 16, 16], C,
                            {"compressor": {"id": "zstd", "level": 1}}),
                           ("1", S2, [4, 8, 8], C,
                            {"compressor": {"id": "zstd", "level": 1}, "seed": 1})])),
    ("partially_empty",
     "one populated chunk among seven all-fill ones; the 3-sample probe sees only fill "
     "and raises the review flag: a sample is evidence, not exhaustive validation",
     lambda p: (pyramid(p, [("0", S1, [8, 16, 16], C, {"payload": "zeros"}),
                            ("1", S2, [4, 8, 8], C, {"seed": 1})]),
                _raw(os.path.join(p, "0", "1.1.1"), _pattern(256, 42)))),
]

# ---------------------------------------------------------------------------
# tifxyz surfaces
# ---------------------------------------------------------------------------

def write_tiff(path: str, arr, *, bigtiff: bool = False) -> None:
    """Minimal uncompressed single-strip TIFF, IFD at the end of the file
    (the layout of the tifxyz files in the public bucket). Deterministic."""
    import struct

    import numpy as np
    arr = np.ascontiguousarray(arr)
    kind = {"f": 3, "u": 1, "i": 2}[arr.dtype.kind]
    data = arr.astype(arr.dtype.newbyteorder("<")).tobytes()
    h, w = arr.shape
    entries = [(256, w), (257, h), (258, arr.dtype.itemsize * 8), (259, 1),
               (262, 1), (273, None), (277, 1), (278, h), (279, len(data)),
               (284, 1), (339, kind)]
    if bigtiff:
        head = struct.pack("<2sHHHQ", b"II", 43, 8, 0, 0)
        data_off = len(head)
        ifd_off = data_off + len(data)
        ifd = struct.pack("<Q", len(entries))
        for tag, val in entries:
            val = data_off if val is None else val
            ifd += struct.pack("<HHQQ", tag, 16 if tag in (273, 279) else 3, 1, val)
        ifd += struct.pack("<Q", 0)
        head = struct.pack("<2sHHHQ", b"II", 43, 8, 0, ifd_off)
    else:
        head = struct.pack("<2sHI", b"II", 42, 0)
        data_off = len(head)
        ifd_off = data_off + len(data)
        ifd = struct.pack("<H", len(entries))
        for tag, val in entries:
            val = data_off if val is None else val
            ifd += struct.pack("<HHII", tag, 4 if tag in (273, 279) else 3, 1, val)
        ifd += struct.pack("<I", 0)
        head = struct.pack("<2sHI", b"II", 42, ifd_off)
    _raw(path, head + data + ifd)


def _surface_xyz(h=6, w=8):
    import numpy as np
    r, c = np.mgrid[0:h, 0:w].astype(np.float32)
    x, y, z = 100 + 2 * c, 200 + 2 * r, 300 + c + r
    for a in (x, y, z):      # invalid corners, marked in every channel
        a[0, 0] = a[-1, -1] = -1.0
    return x, y, z


def _surface_meta(x, y, z, **over):
    import numpy as np
    v = ~((x == -1) | (y == -1) | (z == -1))
    meta = {"format": "tifxyz", "type": "seg", "uuid": "fixture",
            "scale": [0.05, 0.05],
            "bbox": [[float(a[v].min()) for a in (x, y, z)],
                     [float(a[v].max()) for a in (x, y, z)]]}
    meta.update(over)
    return {k: v for k, v in meta.items() if v is not None}


def surface(path, *, meta="auto", channels="xyz", bigtiff=False,
            mutate=None, meta_over=None, **dtype):
    """Write a tifxyz directory; ``mutate(x, y, z)`` edits the grids first."""
    x, y, z = _surface_xyz()
    if mutate:
        x, y, z = mutate(x, y, z)
    os.makedirs(path, exist_ok=True)
    if meta == "auto":
        base_x, base_y, base_z = _surface_xyz()
        _dump(os.path.join(path, "meta.json"),
              _surface_meta(base_x, base_y, base_z, **(meta_over or {})))
    elif meta is not None:
        _text(os.path.join(path, "meta.json"), meta)
    for name, arr in zip("xyz", (x, y, z)):
        if name in channels:
            write_tiff(os.path.join(path, f"{name}.tif"), arr, bigtiff=bigtiff)


def _cells(fn):
    def mutate(x, y, z):
        fn(x, y, z)
        return x, y, z
    return mutate


def _shape_mismatch(x, y, z):
    import numpy as np
    return x, y, np.ascontiguousarray(z[:, :-1])


def _as_uint16(x, y, z):
    import numpy as np
    return tuple(np.clip(a, 0, None).astype(np.uint16) for a in (x, y, z))


TIFXYZ_CASES = [
    ("tifxyz_clean", "clean surface: meta.json + float32 x/y/z, IFD at end of file",
     lambda p: surface(p)),
    ("tifxyz_bigtiff_clean", "clean surface stored as BigTIFF",
     lambda p: surface(p, bigtiff=True)),
    ("tifxyz_meta_missing", "meta.json confirmed absent",
     lambda p: surface(p, meta=None)),
    ("tifxyz_meta_unreadable", "meta.json is truncated JSON",
     lambda p: surface(p, meta='{"format": "tifxyz", "scale": [0.05')),
    ("tifxyz_meta_incomplete", "meta.json says format 'tifxyz' but has no scale",
     lambda p: surface(p, meta_over={"scale": None})),
    ("tifxyz_channel_missing", "z.tif confirmed absent",
     lambda p: surface(p, channels="xy")),
    ("tifxyz_tiff_unreadable", "z.tif is not a TIFF",
     lambda p: (surface(p), _raw(os.path.join(p, "z.tif"), b"not a tiff file"))),
    ("tifxyz_shape_mismatch", "z.tif grid is one column narrower than x and y",
     lambda p: surface(p, mutate=_shape_mismatch)),
    ("tifxyz_sample_format", "channels hold uint16, not floating point",
     lambda p: surface(p, mutate=_as_uint16)),
    ("tifxyz_empty", "every grid cell is -1: no geometry at all",
     lambda p: surface(p, mutate=_cells(lambda x, y, z: [a.fill(-1) for a in (x, y, z)]))),
    ("tifxyz_mask_mismatch", "two cells are -1 in x only",
     lambda p: surface(p, mutate=_cells(lambda x, y, z: x.__setitem__((2, slice(2, 4)), -1)))),
    ("tifxyz_nonfinite", "one valid cell holds NaN in z",
     lambda p: surface(p, mutate=_cells(lambda x, y, z: z.__setitem__((3, 3), float("nan"))))),
    ("tifxyz_bbox_mismatch", "declared bbox is 50 voxels off the stored coordinates",
     lambda p: surface(p, meta_over={"bbox": [[150.0, 202.0, 301.0], [214.0, 210.0, 311.0]]})),
    ("tifxyz_bbox_sentinel",
     "declared bbox minimum is -1: the invalid marker leaked into it (loose, as on 28 public surfaces)",
     lambda p: surface(p, meta_over={"bbox": [[-1.0, -1.0, -1.0], [114.0, 210.0, 311.0]]})),
    ("tifxyz_absent", "requested surface does not exist (nothing to audit)",
     lambda p: None),
]


def build_surfaces(out_dir: str = SURF_DIR) -> None:
    """(Re)build every tifxyz case into ``out_dir``."""
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    for name, _prop, fn in TIFXYZ_CASES:
        fn(os.path.join(out_dir, f"{name}.tifxyz"))


def run_tifxyz_case(name: str, store=None, base: str = SURF_DIR):
    from zpa.httpstore import LocalStore
    from zpa.report import consumer_verdict
    from zpa.tifxyz import audit_surface
    store = store or LocalStore(base)
    report = audit_surface(store, f"{name}.tifxyz", content=True)
    s = report["surface"]
    projection = {
        "integrity": report["integrity"],
        "max_severity": report["max_severity"],
        "kind": report["kind"],
        "evidence": report["evidence"],
        "surface": {"grid": s["grid"], "valid_fraction": s["valid_fraction"],
                    "data_bbox": s["data_bbox"],
                    "content_checked": s["content_checked"],
                    "channels": {c: v.get("state") for c, v in
                                 sorted(s["channels"].items())}},
        "findings": sorted(
            ({k: f[k] for k in ("code", "severity", "level",
                                "evidence_state", "actionable")}
             for f in report["findings"]),
            key=lambda f: (f["level"], f["code"])),
        "consumer_verdict": consumer_verdict(report),
    }
    return projection, report


HTTP_CASES = [
    "http_503_everywhere", "http_403_forbidden", "http_429_level",
    "http_timeout_level", "http_soft_404_html", "http_listing_405",
    "http_listing_hides_header", "http_empty_zarr_dir",
]


def build(out_dir: str = ZARR_DIR) -> None:
    """(Re)build every on-disk case into ``out_dir``."""
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    for name, _prop, fn in ZARR_CASES:
        fn(os.path.join(out_dir, f"{name}.zarr"))
    if out_dir == ZARR_DIR:
        build_surfaces()


# ---------------------------------------------------------------------------
# HTTP replay
# ---------------------------------------------------------------------------

class ReplayResponse:
    def __init__(self, status: int, body: bytes = b"", headers=None):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Length": str(len(body))}
        self.headers.update(headers or {})

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def close(self):
        pass


def _body(spec: dict) -> bytes:
    if "json" in spec:
        return json.dumps(spec["json"]).encode()
    if "text" in spec:
        return spec["text"].encode()
    if "hex" in spec:
        return bytes.fromhex(spec["hex"])
    return b""


def replay_store(routes: dict, *, default_status: int = 404):
    """An ``HttpStore`` whose transport replays ``routes`` (path -> spec)."""
    from zpa.httpstore import HttpStore, StoreError

    store = HttpStore("https://fixture.invalid/", tries=1)

    def request(method, path, **_kw):
        spec = routes.get(path, {"status": default_status})
        if "raise" in spec:
            raise StoreError(f"{method} {path} failed after 1 tries: {spec['raise']}")
        return ReplayResponse(spec["status"], _body(spec), spec.get("headers"))

    store._request = request
    return store


def load_http_case(name: str) -> dict:
    with open(os.path.join(HTTP_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def load_range_cases() -> list[dict]:
    with open(os.path.join(HTTP_DIR, "range-cases.json"), encoding="utf-8") as fh:
        return json.load(fh)["cases"]


# ---------------------------------------------------------------------------
# running a case -> golden projection
# ---------------------------------------------------------------------------

def _gate_args():
    return SimpleNamespace(no_chunk_presence=False, ignore_unreadable=False,
                           fail_on="high")


def project(report: dict, gate: dict, chunk_scan=None) -> dict:
    """Stable, environment-independent projection of one audit."""
    from zpa.report import consumer_verdict

    out = {
        "integrity": report["integrity"],
        "max_severity": report["max_severity"],
        "kind": report["kind"],
        "evidence": report["evidence"],
        "coverage": report["coverage"],
        "levels": [{k: lv[k] for k in (
            "path", "present", "evidence_state", "evidence_reason",
            "shape", "dtype", "has_chunks", "chunk_evidence_state",
            "chunk_evidence_reason")} for lv in report["levels"]],
        "findings": sorted(
            ({k: f[k] for k in ("code", "severity", "level",
                                "evidence_state", "actionable")}
             for f in report["findings"]),
            key=lambda f: (f["level"], f["code"])),
        "gate": {"verdict": gate["verdict"], "fail": gate["fail"],
                 "codes": sorted({f["code"] for f in gate["findings"]})},
        "consumer_verdict": consumer_verdict(report),
    }
    if chunk_scan is not None:
        out["chunk_scan"] = chunk_scan
    return out


def run_store_case(store, root: str, *, scan: bool) -> dict:
    """Audit + gate (+ sampled chunk probe) of one root on any store."""
    from zpa.audit_pyramid import audit_one
    from zpa.chunkscan import classify_level, probe_level
    from zpa.gate import check_one
    from zpa.report import build_report
    from zpa.zarrmeta import read_pyramid

    pm = read_pyramid(store, root)
    findings, level_recs, pyr_rec = audit_one(pm)
    report = build_report(pm, findings=findings, pyramid_record=pyr_rec)
    gate = check_one(store, root, _gate_args())
    chunk_scan = None
    if scan:
        chunk_scan = []
        for rec in level_recs:
            if not rec.get("present") or not rec.get("shape") or not rec.get("chunks"):
                continue
            samples = probe_level(store, root, rec, samples_per_level=3)
            level_findings, all_empty = classify_level(
                root, str(rec["level"]), rec.get("has_chunks"), samples)
            chunk_scan.append({
                "level": str(rec["level"]),
                "samples": [s.status for s in samples],
                "level_codes": sorted({f["code"] for f in level_findings
                                       if f["code"] not in (
                                           "CHUNK_SAMPLE_POPULATED",
                                           "CHUNK_SAMPLE_EMPTY",
                                           "CHUNK_SAMPLE_ABSENT",
                                           "CHUNK_SAMPLE_MISSING")}),
                "all_empty": all_empty,
            })
    return project(report, gate, chunk_scan), report


def run_zarr_case(name: str, store=None, base: str = ZARR_DIR):
    from zpa.httpstore import LocalStore
    store = store or LocalStore(base)
    return run_store_case(store, f"{name}.zarr", scan=True)


def run_http_case(name: str):
    case = load_http_case(name)
    store = replay_store(case["routes"])
    return run_store_case(store, case["root"], scan=False)


def property_of(name: str) -> str:
    for n, prop, _ in ZARR_CASES + TIFXYZ_CASES:
        if n == name:
            return prop
    return load_http_case(name)["property"]


def golden(name: str, projection: dict) -> dict:
    if any(n == name for n, *_ in ZARR_CASES):
        source = f"zarr/{name}.zarr"
    elif any(n == name for n, *_ in TIFXYZ_CASES):
        source = f"surfaces/{name}.tifxyz"
    else:
        source = f"http/{name}.json"
    return {"corpus_version": CORPUS_VERSION, "fixture": name,
            "property": property_of(name), "source": source, **projection}


def all_case_names() -> list[str]:
    return ([n for n, *_ in ZARR_CASES] + list(HTTP_CASES)
            + [n for n, *_ in TIFXYZ_CASES])


def compute(name: str) -> dict:
    if name in HTTP_CASES:
        projection, _ = run_http_case(name)
    elif any(n == name for n, *_ in TIFXYZ_CASES):
        projection, _ = run_tifxyz_case(name)
    else:
        projection, _ = run_zarr_case(name)
    return golden(name, projection)


def write_expected() -> None:
    os.makedirs(EXPECTED_DIR, exist_ok=True)
    for name in all_case_names():
        _dump(os.path.join(EXPECTED_DIR, f"{name}.json"), compute(name))


def case_table() -> str:
    """The README's case table, rendered from the committed goldens."""
    rows = ["| case | property isolated | findings (severity, evidence) "
            "| integrity | gate | chunk probe / surface content |",
            "|---|---|---|---|---|---|"]
    for name in all_case_names():
        with open(os.path.join(EXPECTED_DIR, f"{name}.json"), encoding="utf-8") as fh:
            g = json.load(fh)
        findings = ", ".join(
            f"`{f['code']}` ({f['severity']}, {f['evidence_state']})"
            for f in g["findings"]) or "—"
        scan = "—"
        if "chunk_scan" in g:
            statuses = sorted({x for lv in g["chunk_scan"] for x in lv["samples"]})
            codes = sorted({c for lv in g["chunk_scan"] for c in lv["level_codes"]})
            scan = ", ".join(statuses) + (
                "; " + ", ".join(f"`{c}`" for c in codes) if codes else "")
            scan = scan or "—"
        if "surface" in g:
            vf = g["surface"]["valid_fraction"]
            scan = "—" if vf is None else f"content: {vf:.0%} valid"
        gate = g["gate"]["verdict"] if "gate" in g else "—"
        rows.append(f"| `{name}` | {g['property']} | {findings} | "
                    f"{g['integrity']} | {gate} | {scan} |")
    return "\n".join(rows) + "\n"


def write_readme_table() -> None:
    """Replace everything after '## Cases' in fixtures/README.md."""
    path = os.path.join(HERE, "README.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    head = text[:text.index("## Cases")]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head + "## Cases\n\n" + case_table())


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["build"]:
        build()
    elif argv == ["expected"]:
        write_expected()
        write_readme_table()
    elif argv == ["readme"]:
        write_readme_table()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
