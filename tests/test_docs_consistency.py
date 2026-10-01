"""Docs must not drift from the code.

Guards the drift classes that actually happened: documented flags that no
longer exist, a README check-code list that disagrees with ``SEVERITY``, and
dashboard descriptions missing for a code. If one of these fails, fix the docs
(or ``SEVERITY``) -- do not delete the test.
"""
import contextlib
import importlib
import io
import re
import tomllib
from pathlib import Path

import pytest

from zpa.audit_pyramid import SEVERITY
from zpa.build_dashboard import CODE_BLURB

ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = [ROOT / "README.md", ROOT / "AGENTS.md",
             ROOT / ".github" / "CONTRIBUTING.md"]
FENCE = re.compile(r"```(?:bash|shell|sh)?\n(.*?)```", re.S)
COMMAND = re.compile(r"\s*(?:\w+=\S+\s+)*(zpa-[a-z-]+)(.*)")
FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def _scripts() -> dict[str, str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return pyproject["project"]["scripts"]


def _help_flags(script: str, monkeypatch) -> set[str]:
    module, func = _scripts()[script].split(":")
    monkeypatch.setattr("sys.argv", [script, "--help"])
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as exc:
        getattr(importlib.import_module(module), func)()
    assert exc.value.code in (0, None), f"{script} --help did not exit 0"
    return set(FLAG.findall(out.getvalue()))


def _documented_commands(text: str):
    """Yield (command, args) for every zpa-* line in a fenced shell block."""
    for block in FENCE.findall(text):
        # join `\` continuations; strip trailing ` # comment`
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            m = COMMAND.match(re.sub(r"\s#.*$", "", line))
            if m:
                yield m.group(1), m.group(2)


def _doc_files():
    present = [p for p in DOC_FILES if p.exists()]
    if not present:
        pytest.skip("repo docs not available (running outside a checkout)")
    return present


def test_documented_commands_exist_and_use_real_flags(monkeypatch):
    scripts = _scripts()
    problems = []
    for path in _doc_files():
        for command, args in _documented_commands(path.read_text()):
            if command not in scripts:
                problems.append(f"{path.name}: unknown command {command}")
                continue
            valid = _help_flags(command, monkeypatch)
            for flag in FLAG.findall(args):
                if flag not in valid:
                    problems.append(f"{path.name}: {command} has no {flag}")
    assert not problems, "\n".join(problems)


def test_docs_do_not_use_doubled_backslash_continuations():
    """`\\\\` at end of line in a shell fence breaks copy-paste."""
    problems = []
    for path in _doc_files():
        for block in FENCE.findall(path.read_text()):
            problems += [f"{path.name}: {line.strip()[:60]}"
                         for line in block.splitlines()
                         if line.rstrip().endswith("\\\\")]
    assert not problems, "\n".join(problems)


def test_readme_check_codes_match_severity():
    readme = ROOT / "README.md"
    if not readme.exists():
        pytest.skip("README not available")
    listed = dict(re.findall(r"^([A-Z][A-Z_]+)\s+\[(\w+)\]", readme.read_text(), re.M))
    assert listed == SEVERITY, (
        "README check-code list is out of sync with SEVERITY: "
        f"missing={sorted(set(SEVERITY) - set(listed))} "
        f"extra={sorted(set(listed) - set(SEVERITY))} "
        f"wrong severity={sorted(c for c in listed if c in SEVERITY and listed[c] != SEVERITY[c])}"
    )


def test_dashboard_describes_every_check_code():
    missing = sorted(set(SEVERITY) - set(CODE_BLURB))
    assert not missing, f"add CODE_BLURB entries in build_dashboard.py: {missing}"
