#!/usr/bin/env python3
"""Compare verified vs mismatching shards at the byte level."""

import csv
import struct
import urllib.request


def crc32c_bitwise(data: bytes) -> int:
    poly = 0x82F63B78
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


def fetch_suffix(url: str, n: int) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes=-{n}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        return data[-n:] if len(data) >= n else data


def analyze(url: str, idx_size: int, label: str):
    print(f"--- {label} ---")
    print(f"URL: {url}")
    raw = fetch_suffix(url, idx_size)
    print(f"Fetched {len(raw)} bytes (expected {idx_size})")

    stored = int.from_bytes(raw[-4:], "little")
    computed = crc32c_bitwise(raw[:-4])
    print(f"Stored: 0x{stored:08x}, Computed: 0x{computed:08x}, Match: {stored == computed}")

    # Look at index entries
    n_inner = (len(raw) - 4) // 16
    # Count missing vs present
    missing = 0
    present = 0
    for i in range(min(n_inner, 1000)):
        off, ln = struct.unpack_from("<QQ", raw, i * 16)
        if off == 2**64 - 1:
            missing += 1
        else:
            present += 1
    print(f"n_inner={n_inner}, missing={missing}, present={present} (first 1000)")

    # Hex dump of last 32 bytes before checksum
    print(f"Last 32 index bytes: {raw[-36:-4].hex()}")
    print(f"Checksum bytes: {raw[-4:].hex()}")
    print()


def main():
    findings = "artifacts/2026-10-02-crc-validation/scan_empty_chunks.findings.csv"
    base = "https://dl.ash2txt.org/"

    # Find a verified shard and a mismatching shard from same volume/level if possible
    with open(findings) as f:
        rows = list(csv.DictReader(f))

    # Get mismatches
    mismatches = [r for r in rows if r["code"] == "SHARD_INDEX_CHECKSUM_MISMATCH"]
    print(f"Total mismatches: {len(mismatches)}")

    # For verified, we need to look at the summary or find shards that were sampled
    # Let's just test the first mismatch in detail
    m = mismatches[0]
    url = f"{base}{m['root']}/{m['level']}/c/{m['chunk'].replace('.', '/')}"
    analyze(url, int(m["bytes_fetched"]), "MISMATCH example")


if __name__ == "__main__":
    main()
