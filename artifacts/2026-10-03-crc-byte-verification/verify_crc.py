#!/usr/bin/env python3
"""Byte-level verification of SHARD_INDEX_CHECKSUM_MISMATCH findings.

Picks mismatching shards from the 2026-10-02 CRC campaign and re-verifies
them with a completely independent CRC-32C implementation (bit-by-bit,
no lookup table) against raw HTTP-fetched bytes.

This determines whether the 16.5% mismatch rate is:
  (a) real writer non-conformance, or
  (b) a zpa implementation bug (wrong byte domain, wrong checksum coverage)
"""

import csv
import struct
import sys
import urllib.request


def crc32c_bitwise(data: bytes) -> int:
    """Independent CRC-32C: bit-by-bit, no table, reflected polynomial."""
    poly = 0x82F63B78  # CRC-32C (Castagnoli), reflected
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


def fetch_suffix(url: str, n: int) -> bytes:
    """Fetch the last n bytes via HTTP Range request."""
    req = urllib.request.Request(url, headers={"Range": f"bytes=-{n}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (200, 206):
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        data = resp.read()
        # If server ignored Range and sent full object, take the tail
        return data[-n:] if len(data) >= n else data


def main():
    findings = "artifacts/2026-10-02-crc-validation/scan_empty_chunks.findings.csv"
    base = "https://dl.ash2txt.org/"

    mismatches = []
    with open(findings) as f:
        for row in csv.DictReader(f):
            if row["code"] == "SHARD_INDEX_CHECKSUM_MISMATCH":
                mismatches.append(row)

    print(f"Found {len(mismatches)} mismatch findings in CSV")
    print()

    # Test first 3 mismatches
    for i, m in enumerate(mismatches[:3]):
        root = m["root"]
        level = m["level"]
        chunk = m["chunk"]  # e.g. "0.0.0"
        coords = chunk.replace(".", "/")
        url = f"{base}{root}/{level}/c/{coords}"
        idx_size = int(m["bytes_fetched"])

        print(f"--- Mismatch {i+1}: {root} level {level} chunk {chunk} ---")
        print(f"URL: {url}")
        print(f"Index size from CSV: {idx_size} bytes")

        try:
            raw = fetch_suffix(url, idx_size)
        except Exception as e:
            print(f"  FETCH FAILED: {e}")
            continue

        print(f"  Fetched {len(raw)} bytes")
        if len(raw) != idx_size:
            print(f"  WARNING: fetched size != expected size")

        # Independent verification
        stored = int.from_bytes(raw[-4:], "little")
        computed = crc32c_bitwise(raw[:-4])

        print(f"  Stored checksum:   0x{stored:08x}")
        print(f"  Computed (indep):  0x{computed:08x}")
        print(f"  Match: {stored == computed}")

        # Also try: checksum over raw including the 4 bytes? (shouldn't match)
        # And: what does the index look like?
        n_inner = (len(raw) - 4) // 16
        print(f"  Implied n_inner: {n_inner}")

        # Check first few index entries for sanity
        entries = struct.unpack_from(f"<{min(4, n_inner)*2}Q", raw[:min(4, n_inner)*32])
        print(f"  First entries (offset, length): {list(zip(entries[::2], entries[1::2]))[:2]}")
        print()


if __name__ == "__main__":
    main()
