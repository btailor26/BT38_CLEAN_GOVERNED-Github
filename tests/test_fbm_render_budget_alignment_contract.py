from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUDGET = (ROOT / "services" / "governed_fbm_render_budget_alignment.py").read_text(encoding="utf-8")
SEARCH = (ROOT / "services" / "governed_fbm_global_search_alignment.py").read_text(encoding="utf-8")
CURRENT_AMAZON = (ROOT / "services" / "governed_fbm_current_amazon_profile_alignment.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_fbm_render_budget_is_browser_local_presentation_only():
    assert "_PAGE_SIZE = 15" in BUDGET
    assert "_PAGE_SIZES = (15, 30, 50, 100)" in BUDGET
    assert "page_alignment._expand_control = _expand_control" in BUDGET
    assert 'id="bt38FbmOrderFlow"' in BUDGET
    assert 'id="bt38ResultsPerPageSelect"' in BUDGET
    assert 'id="bt38FbmPreviousPage"' in BUDGET
    assert 'id="bt38FbmNextPage"' in BUDGET
    assert "install_governed_fbm_render_budget_alignment(app)" in MAIN
    assert MAIN.index("install_governed_fbm_global_search_alignment(app)") < MAIN.index("install_governed_fbm_render_budget_alignment(app)")


def test_fbm_render_budget_keeps_page_read_db_only_and_never_marketplace_provider_polling():
    assert "db.session.query" not in BUDGET
    assert "requests." not in BUDGET
    assert "fetch(" not in BUDGET
    assert "EventSource" not in BUDGET
    assert "setInterval" not in BUDGET
    assert "setTimeout" not in BUDGET
    assert "app.view_functions" not in BUDGET


def test_fbm_page_time_amazon_hydration_remains_disabled():
    assert "Compatibility no-op" in CURRENT_AMAZON
    assert "return None" in CURRENT_AMAZON
    assert "before_request" not in CURRENT_AMAZON
    assert "get_or_refresh_amazon_profile" not in CURRENT_AMAZON
    assert "no page-time Amazon hydration" in CURRENT_AMAZON
