#!/usr/bin/env python3
"""Test alternative checksum hypotheses for the mismatching shards."""

import csv
import urllib.request
import zlib


def crc32c_bitwise(data: bytes) -> int:
    poly = 0x82F63B78
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


def crc32_ieee_bitwise(data: bytes) -> int:
    """CRC-32 IEEE (zlib polynomial), bit-by-bit."""
    poly = 0xEDB88320
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


def main():
    findings = "artifacts/2026-10-02-crc-validation/scan_empty_chunks.findings.csv"
    base = "https://dl.ash2txt.org/"

    with open(findings) as f:
        rows = [r for r in csv.DictReader(f) if r["code"] == "SHARD_INDEX_CHECKSUM_MISMATCH"]

    m = rows[0]
    url = f"{base}{m['root']}/{m['level']}/c/{m['chunk'].replace('.', '/')}"
    raw = fetch_suffix(url, int(m["bytes_fetched"]))

    stored_le = int.from_bytes(raw[-4:], "little")
    stored_be = int.from_bytes(raw[-4:], "big")
    index_bytes = raw[:-4]

    print(f"Stored (LE): 0x{stored_le:08x}")
    print(f"Stored (BE): 0x{stored_be:08x}")
    print()

    hypotheses = [
        ("CRC-32C over index", crc32c_bitwise(index_bytes)),
        ("CRC-32 IEEE over index", crc32_ieee_bitwise(index_bytes)),
        ("CRC-32C over index+checksum", crc32c_bitwise(raw)),
        ("zlib.crc32 over index", zlib.crc32(index_bytes) & 0xFFFFFFFF),
    ]

    for name, computed in hypotheses:
        match_le = "MATCH-LE" if computed == stored_le else ""
        match_be = "MATCH-BE" if computed == stored_be else ""
        print(f"{name:30s} 0x{computed:08x}  {match_le} {match_be}")

    print()
    print("If none match: writer is non-conforming OR checksum covers different bytes.")


if __name__ == "__main__":
    main()
