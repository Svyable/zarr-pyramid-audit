# G2 Byte-Level CRC Verification — 2026-10-03

## Question

The 2026-10-02 CRC campaign found 331 `SHARD_INDEX_CHECKSUM_MISMATCH`
findings (16.5% of 2,008 shards). Is zpa's `verify_index_checksum()`
wrong, or is the volcomp writer non-conforming?

## Method

Independent byte-level verification using a bit-by-bit CRC-32C
implementation (no lookup table, completely separate from zpa's
table-driven code) against raw HTTP-fetched shard tail bytes.

Tested hypotheses:
- CRC-32C (Castagnoli) over index bytes → **no match**
- CRC-32 IEEE over index bytes → **no match**
- CRC-32C over index + checksum bytes → **no match**
- Different byte orders (LE/BE) for stored checksum → **no match**

## Results

3 mismatching shards tested, all confirmed by independent implementation:
- `PHerc0125` level 4 chunk 0.0.0: stored `0x1643fe4c`, computed `0x17b24ef1`
- `PHerc0125` level 4 chunk 1.0.0: stored `0x07e19d14`, computed `0x72e2d03b`
- `PHerc0125` level 5 chunk 0.0.0: stored `0x3441922f`, computed `0xd1a3af90`

## Conclusion

**The volcomp writer is non-conforming.** zpa's implementation is correct:
- 1,167 shards (58.1%) verify correctly with the same code path
- If zpa had a bug, all shards would fail, not 16.5%
- The metadata (`index_codecs: [bytes, crc32c]`, `index_location: end`)
  confirms zpa's byte-domain interpretation

## Correlation analysis

- 39 of 64 volumes affected
- Higher levels (4, 5) overrepresented: 111 + 80 = 191 of 331 (58%)
- Edge shards (any coord=0): 252 of 331 (76%)

The edge-shard correlation suggests the writer's checksum bug may relate
to partial-shard handling, but the root cause is in the writer, not zpa.

## Severity decision

**Raised from `low` to `medium`.**

Rationale:
- The code comment said "low until a live run shows mismatches are rare"
- 16.5% is not rare — it's a systematic writer defect
- `medium` = human review, which is appropriate: the index parses and
  chunks decode, but the integrity guarantee is void
- NOT `high`: the data itself is intact (decodes correctly); `high` would
  mean "do not train" which is disproportionate
- zpa already fails closed: mismatching shards are not sampled

## Files

- `verify_crc.py`: independent verification script
- `test_hypotheses.py`: alternative checksum hypothesis testing
- `analyze_crc.py`: shard structure analysis
