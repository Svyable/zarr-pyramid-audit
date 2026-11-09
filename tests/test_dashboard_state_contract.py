"""Generated/public Zarr audit dashboard state-machine contract."""

from pathlib import Path

from zpa.build_dashboard import PAGE


def _script(page: str) -> str:
    return page.split("<script>", 1)[1].split("</script>", 1)[0]


def test_dashboard_script_cannot_drift_from_published_page():
    generated = _script(PAGE).replace("{{", "{").replace("}}", "}")
    published = _script(Path("docs/index.html").read_text(encoding="utf-8"))
    assert generated == published


def test_dashboard_has_validated_keyboard_accessible_linkable_view_state():
    js = _script(PAGE)
    for event in ('case "sort":', 'case "severity":', 'case "query":', 'case "reset":'):
        assert event in js
    for guard in ("SORT_KEYS.has(value)", "SEVERITIES.has(value)", "SORT_KEYS.has(sort)", "SEVERITIES.has(severity)"):
        assert guard in js
    assert 'b.setAttribute("aria-pressed", String(selected))' in js
    assert 'th.setAttribute("aria-sort",' in js
    assert 'th.addEventListener("keydown",' in js
    assert "window.history.replaceState(" in js
    assert "url.searchParams.delete(k)" in js
    assert "url.pathname + url.search + url.hash" in js
    assert "Object.assign(view, DEFAULT)" in js
    assert 'id="resetCodes"' in PAGE
    assert 'id="resetCodes"' in Path("docs/index.html").read_text(encoding="utf-8")
