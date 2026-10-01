| tool | defects flagged | suspicious content flagged | false alarms on valid pyramids | out-of-model nodes identified |
|---|---|---|---|---|
| zarr-python | 8 / 26 | 0 / 3 | 0 / 10 | 1 / 4 |
| ome-zarr-models | 14 / 26 | 0 / 3 | 0 / 10 | 4 / 4 |
| zpa (header audit) | 25 / 26 | 0 / 3 | 1 / 10 | 4 / 4 |
| zpa (+ chunk probe) | 26 / 26 | 3 / 3 | 2 / 10 | 4 / 4 |

Per fixture (✓ = the tool gave its user a signal):

| fixture | truth | zarr-python | ome-zarr-models | ZPA integrity / codes | ZPA chunk probe |
|---|---|---|---|---|---|
| `clean_v2` | benign | · silent | · accepts | PASS — | — |
| `clean_v3` | benign | · silent | · accepts | PASS — | — |
| `missing_level` | defect | ✓ raises | ✓ rejects | FAIL LEVEL_MISSING | — |
| `level_no_chunks` | defect | · silent | · accepts | FAIL LEVEL_NO_CHUNKS | CHUNK_LEVEL_NO_CHUNKS |
| `level_undeclared` | defect | · silent | · accepts | WARN LEVEL_UNDECLARED | — |
| `scale_shape_mismatch` | defect | · silent | · accepts | FAIL SCALE_SHAPE_MISMATCH | — |
| `mixed_rounding` | defect | · silent | · accepts | WARN MIXED_ROUNDING | — |
| `scale_nonmonotonic` | defect | · silent | · accepts | WARN SCALE_NONMONOTONIC | — |
| `dtype_drift` | defect | · silent | · accepts | FAIL DTYPE_DRIFT | — |
| `fill_drift` | defect | · silent | · accepts | WARN FILL_DRIFT | — |
| `compressor_drift` | benign | · silent | · accepts | PASS COMPRESSOR_DRIFT | — |
| `separator_drift` | defect | · silent | · accepts | FAIL SEPARATOR_DRIFT | — |
| `ndim_drift` | defect | · silent | ✓ rejects | FAIL NDIM_DRIFT | — |
| `axes_mismatch` | defect | · silent | ✓ rejects | PASS AXES_MISMATCH | — |
| `degenerate_level` | defect | · silent | · accepts | FAIL DEGENERATE_LEVEL, LEVEL_NO_CHUNKS, SCALE_SHAPE_MISMATCH | CHUNK_LEVEL_NO_CHUNKS |
| `chunk_exceeds_shape` | benign | · silent | · accepts | PASS CHUNK_EXCEEDS_SHAPE | — |
| `physical_scale_unknown` | benign | · silent | · accepts | PASS PHYSICAL_SCALE_UNKNOWN | — |
| `physical_scale_contradiction_units` | defect | · silent | · accepts | FAIL PHYSICAL_SCALE_CONTRADICTION | — |
| `physical_scale_contradiction_scale` | defect | · silent | · accepts | FAIL PHYSICAL_SCALE_CONTRADICTION | — |
| `physical_scale_unspecified` | benign | · silent | · accepts | PASS — | — |
| `ome_version_unmodelled` | out-of-model | · silent | ✓ rejects | PASS OME_VERSION_UNMODELLED | — |
| `transform_scale_count` | defect | · silent | ✓ rejects | PASS TRANSFORM_SCALE_COUNT | — |
| `transform_arity` | defect | · silent | ✓ rejects | PASS TRANSFORM_ARITY | — |
| `dimension_names_missing` | defect | · silent | ✓ rejects | PASS DIMENSION_NAMES_MISMATCH | — |
| `axes_invalid` | defect | · silent | ✓ rejects | PASS AXES_INVALID | — |
| `multiscale_empty` | defect | · silent | ✓ rejects | FAIL MULTISCALE_EMPTY | — |
| `not_multiscale` | out-of-model | · silent | ✓ rejects | PASS NOT_MULTISCALE | — |
| `bare_array` | out-of-model | · silent | ✓ rejects | PASS BARE_ARRAY | — |
| `headerless_chunk_store` | defect | ✓ raises | ✓ rejects | FAIL HEADERLESS_CHUNK_STORE | — |
| `container_no_group_header` | defect | ✓ raises | ✓ rejects | PASS CONTAINER_NO_GROUP_HEADER | — |
| `not_a_zarr_group` | out-of-model | ✓ raises | ✓ rejects | PASS NOT_A_ZARR_GROUP | — |
| `root_absent` | defect | ✓ raises | ✓ rejects | UNKNOWN ROOT_ABSENT | — |
| `malformed_zgroup` | defect | ✓ raises | ✓ rejects | FAIL METADATA_UNREADABLE | — |
| `malformed_zattrs` | defect | ✓ raises | ✓ rejects | FAIL METADATA_UNREADABLE | — |
| `malformed_level_header` | defect | ✓ raises | ✓ rejects | FAIL METADATA_UNREADABLE | — |
| `present_all_fill` | suspicious | · silent | · accepts | PASS — | CHUNK_SAMPLE_ALL_EMPTY |
| `zero_data_nonzero_fill` | benign | · silent | · accepts | PASS — | — |
| `nan_fill_all_empty` | suspicious | · silent | · accepts | PASS — | CHUNK_SAMPLE_ALL_EMPTY |
| `sparse_level` | benign | · silent | · accepts | PASS — | — |
| `all_fill_nonzero` | suspicious | · silent | · accepts | PASS — | CHUNK_SAMPLE_ALL_EMPTY |
| `sparse_unsampled` | benign | · silent | · accepts | PASS — | CHUNK_LEVEL_NO_SAMPLES |
| `undecodable_codec` | defect | ✓ raises | · accepts | PASS — | CHUNK_UNDECODEABLE |
| `partially_empty` | benign | · silent | · accepts | PASS — | CHUNK_SAMPLE_ALL_EMPTY |

Versions: zarr 3.1.6, ome-zarr-models 1.7, zarr-pyramid-audit 0.4.0, fixture corpus 1
