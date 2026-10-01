"""Mutation checks: break each guard in a THROWAWAY COPY and confirm tests fail.

Run from the repo root:  python artifacts/log-2026-10-01/mutation_checks.py
The working tree is never modified; each mutation is applied to a temp copy.
A guard whose removal does not make any test fail is untested and reported.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MUTATIONS = [
    ("version gate never fires (max version 9.9)", "src/zpa/audit_pyramid.py",
     "_MODELLED_OME_MAX = (0, 5)", "_MODELLED_OME_MAX = (9, 9)"),
    ("transform checks judged for every version", "src/zpa/audit_pyramid.py",
     "transforms_apply = parsed >= (0, 4)", "transforms_apply = True"),
    ("scanner never verifies the index crc32c", "src/zpa/chunkscan.py",
     "crc_ok = vc.verify_index_checksum(raw_index, info.index_codecs)",
     "crc_ok = None"),
    ("stored checksum read big-endian", "src/zpa/volcomp.py",
     'int.from_bytes(raw[-4:], "little")', 'int.from_bytes(raw[-4:], "big")'),
    ("arity reported even when the axes list is the odd one out",
     "src/zpa/audit_pyramid.py",
     "                        and len(axes_raw) != len(lm.shape)\n",
     "                        and False\n"),
    ("start-located index not refused", "src/zpa/chunkscan.py",
     'if info.index_location != "end":', "if False:"),
]


def run_tests(tree: Path) -> tuple[bool, str]:
    """Return (all_passed, pytest's one-line summary)."""
    env = {"PYTHONPATH": str(tree / "src"), "PATH": "/usr/bin:/usr/local/bin"}
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                        "-p", "no:cacheprovider"],
                       cwd=tree, env=env, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l]
    return r.returncode == 0, (lines[-1] if lines else r.stderr[-200:])


def main() -> int:
    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.egg-info", "tmp")
    ok, summary = run_tests(ROOT)
    print("baseline (unmutated):", summary)
    if not ok:
        print("!! baseline is not green; mutation results would be meaningless")
        return 2
    untested = 0
    for name, rel, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as td:
            tree = Path(td) / "repo"
            shutil.copytree(ROOT, tree, ignore=ignore)
            f = tree / rel
            text = f.read_text()
            if old not in text:
                print(f"!! {name}: pattern not found in {rel} (stale script)")
                untested += 1
                continue
            f.write_text(text.replace(old, new, 1))
            all_passed, result = run_tests(tree)
            caught = not all_passed
            untested += not caught
            print(f"{'caught  ' if caught else 'UNTESTED'} {name}: {result}")
    return 1 if untested else 0


if __name__ == "__main__":
    raise SystemExit(main())
