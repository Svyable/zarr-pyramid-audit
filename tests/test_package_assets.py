"""Required decoder resources must survive sdist -> wheel -> installation."""
import ctypes
from importlib.resources import as_file, files
import platform

import pytest


def test_decoder_and_provenance_are_packaged():
    data = files("zpa").joinpath("data")
    binary = data.joinpath("libvolcomp-linux-x86_64.so")
    assert binary.is_file()
    assert binary.read_bytes().startswith(b"\x7fELF")
    provenance = data.joinpath("VOLCOMP_PROVENANCE.md").read_text()
    assert "libvolcomp-linux-x86_64.so" in provenance
    assert "MIT" in provenance


@pytest.mark.skipif(
    platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"),
    reason="vendored decoder supports Linux x86-64 only",
)
def test_packaged_decoder_loads():
    binary = files("zpa").joinpath("data", "libvolcomp-linux-x86_64.so")
    with as_file(binary) as path:
        ctypes.CDLL(str(path))
