| root | levels | header audit: time · requests (meta/list/head) · payload | findings | chunk probe: time · reads · payload | probe result |
|---|---|---|---|---|---|
| `1.129um-0.22m-59keV-volume-20260521123630-L1.zarr` | 6 | 1.77 s · 16 (8/6/2) · 4.6 KiB | LEVEL_NO_CHUNKS (FAIL) | 4.35 s · 0 reads + 41 HEAD · 0 B | CHUNK_LEVEL_NO_CHUNKS |
| `2.399um-0.22m-78keV-volume-20260309142202.zarr` | 6 | 1.50 s · 16 (8/6/2) · 4.6 KiB | none (PASS) | 5.39 s · 20 reads + 19 HEAD · 5.0 MiB | populated 17 |
| `8.64um-1.2m-116keV-volume-20250521151220.zarr` | 6 | 1.75 s · 16 (8/6/2) · 3.6 KiB | none (PASS) | 1.23 s · 13 reads + 25 HEAD · 877.7 KiB | populated 13; CHUNK_LEVEL_NO_SAMPLES |
| `20260319104112-surface-20260413222639-surface-m7-L2-th0.2.zarr` | 6 | 1.52 s · 16 (8/6/2) · 5.3 KiB | none (PASS) | 6.64 s · 12 reads + 46 HEAD · 2.8 MiB | populated 12 |
| `20250521140437-8.640um-1.2m-116keV-masked.zarr` | 6 | 1.47 s · 16 (8/6/2) · 4.4 KiB | none (PASS) | 6.89 s · 21 reads + 33 HEAD · 8.1 MiB | populated 17 |
| `PHercParis4-20260603024952-2.4um-0.22m-78keV-volume-20260411134726-L2-3d-ink-max.zarr` | 6 | 2.30 s · 22 (14/6/2) · 8.9 KiB | none (PASS) | not measured (sharded v3) | — |
