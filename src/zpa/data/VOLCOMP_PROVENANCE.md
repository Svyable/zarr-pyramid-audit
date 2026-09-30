# Vendored volcomp decoder — provenance

`libvolcomp-linux-x86_64.so` (166 KB) is a vendored build of the **volcomp**
lossy CT codec, used only to *decode* (never encode) chunk payloads when
probing Zarr v3 `sharding_indexed` levels whose inner codec is `volcomp`
(the `dl.ash2txt.org` scroll volumes).

- Upstream: https://github.com/superoptimizer/volume-compressor
- Commit: `3e549a345fde0a668a37bf248137e78317e3489f` (2026-09-25)
- License: MIT (see upstream LICENSE; compatible with this repo's MIT)
- Built: `cmake -S . -B build -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_C_COMPILER=gcc -DCMAKE_C_FLAGS="-Wno-error=sign-conversion" &&
  cmake --build build --target volcomp_shim -j4`
  (upstream targets clang; the single `-Wsign-conversion` diagnostic is
  relaxed for the gcc build — no source changes)
- Self-test: upstream `python/test_ctypes.py` → PASS

Why vendored instead of built at install time: the probe must work from a
plain `pip install` with no C toolchain, and the decoder is a stable,
single-file-header C library (the whole codec is `volcomp.h`).

To rebuild or audit: clone the upstream repo at the commit above and run
the build commands. To override at runtime without touching this file:

    VOLCOMP_LIB=/path/to/libvolcomp.so zpa-scan-chunks ...

The vendored binary is Linux x86-64 only. On other platforms the volcomp
probe path is skipped with a clear message; every other tool is unaffected.
