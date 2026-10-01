# Surface-volume depth profile

`zpa-surface-depth-profile` audits the rendered 2.5D surface-volume input used by ink models. It is deliberately an **evidence tool, not an ink detector**.

A Zarr can be structurally valid while still being the wrong model input: the render may contain the wrong number of slices, sampled depth layers can be all zero, or layers can be duplicated. Ink models can also be sensitive to depth offset, so the report records where sampled gradient energy and dynamic range peak relative to the nominal middle of the stack.

## Example: released 9 µm model input

```bash
zpa-surface-depth-profile \
  --surface-volume /data/w035_9um.zarr \
  --expected-depth 28 \
  --source-volume-id 20250728140407-9.362um-1.2m-113keV-masked \
  --expected-volume-id 20250728140407-9.362um-1.2m-113keV-masked \
  --grid 3 --tile-size 128 \
  --out-dir out/w035-depth
```

For a 21-slice aligned training representation, use `--expected-depth 21`. The expected-depth check is the only fail/exit-code gate. All-zero sampled layers, duplicate sampled-layer digests, peak-gradient depth, and peak dynamic-range depth are reported as evidence because legitimate surface volumes can contain background or unusual depth profiles.

## Sampling

The tool assumes array order `[depth, y, x]`. It samples a deterministic grid of XY tiles at every selected depth (`--depth-stride 1` by default) and records:

- finite and nonzero fractions;
- mean, standard deviation, p01/p50/p99 and p99-p01 dynamic range;
- XY gradient energy;
- whether every sampled voxel at that depth is zero;
- a canonical SHA-256 digest of sampled values, used to expose duplicate sampled layers.

The run also uses zarr-pyramid-audit's standard manifest and no-silent-overwrite behavior, so the depth evidence can be pinned into a larger submission provenance graph.
