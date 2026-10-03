from __future__ import annotations

import json
from pathlib import Path


def test_oztest_pin_is_traceable_and_not_silently_reclassified():
    path = Path(__file__).parents[1] / "fixtures" / "external" / "oztest-pin.json"
    pin = json.loads(path.read_text(encoding="utf-8"))

    source = pin["source"]
    assert source["status"] == "reference-only"
    assert source["licensing"] == "blocked"
    assert len(source["commit"]) == 40

    cases = pin["cases"]
    assert cases
    assert len({case["slug"] for case in cases}) == len(cases)

    for case in cases:
        assert len(case["blob_sha"]) == 40
        if case["expected"] == "valid":
            assert "/valid/" in case["slug"]
        elif case["expected"] == "invalid":
            assert "/invalid/" in case["slug"]
        else:
            raise AssertionError(f"unexpected classification: {case['expected']}")
