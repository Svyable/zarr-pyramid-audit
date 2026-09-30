#!/usr/bin/env python3
"""Shim: runs the installed zpa package, or src/ from a checkout."""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from zpa.gate import main

if __name__ == "__main__":
    raise SystemExit(main())
