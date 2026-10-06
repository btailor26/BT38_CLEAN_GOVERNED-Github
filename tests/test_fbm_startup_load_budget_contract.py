from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fbm_startup_defers_qz_library_until_printing_is_used():
    template = (ROOT / "templates" / "fbm.html").read_text(encoding="utf-8")
    qz = (ROOT / "static" / "js" / "fbm_qz_print.js").read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net/npm/qz-tray@2.2.6/qz-tray.js" not in template
    assert "data-bt38-qz-lazy" not in template
    assert "script.dataset.bt38QzLazy = '1'" in qz
    assert "const qz = await requireQz();" in qz


def test_ordinary_page_navigation_does_not_fetch_dashboard_for_assistant():
    source = (ROOT / "static" / "js" / "bt38-live-page-refresh.js").read_text(encoding="utf-8")
    assert "if (!(options && options.committedEvent === true))" in source
    assert "void refreshAssistant({committedEvent:true});" in source
    assert "const count = await readDashboardActionCount(options);" in source
