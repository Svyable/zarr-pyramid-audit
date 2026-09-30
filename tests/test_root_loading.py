from types import SimpleNamespace
import json

from zpa.audit_pyramid import load_roots


def test_load_roots_deduplicates_preserving_first_seen_order(tmp_path):
    roots_file = tmp_path / "roots.jsonl"
    roots_file.write_text("\n".join(json.dumps({"root": r}) for r in ["b", "a", "b", "c"]))
    args = SimpleNamespace(root=["a", "d"], roots=str(roots_file))
    assert load_roots(args) == ["a", "d", "b", "c"]


def test_load_roots_skips_malformed_lines(tmp_path):
    roots_file = tmp_path / "roots.jsonl"
    roots_file.write_text('{"root":"ok"}\nnot-json\n{}\n')
    args = SimpleNamespace(root=None, roots=str(roots_file))
    assert load_roots(args) == ["ok"]
