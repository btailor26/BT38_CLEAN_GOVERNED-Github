from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUDGET = (ROOT / "services" / "governed_fbm_render_budget_alignment.py").read_text(encoding="utf-8")
SEARCH = (ROOT / "services" / "governed_fbm_global_search_alignment.py").read_text(encoding="utf-8")
CURRENT_AMAZON = (ROOT / "services" / "governed_fbm_current_amazon_profile_alignment.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_fbm_first_render_keeps_existing_snapshot_but_caps_candidate_hydration():
    assert "_SESSION_MAX_ROWS = 300" in SEARCH
    assert "candidate_limit = (_SESSION_MAX_ROWS * _SESSION_CANDIDATE_MULTIPLIER) + 1" in SEARCH
    assert "session_alignment._SESSION_CANDIDATE_MULTIPLIER = 1" in BUDGET
    assert "install_governed_fbm_render_budget_alignment(app)" in MAIN
    assert MAIN.index("install_governed_fbm_global_search_alignment(app)") < MAIN.index("install_governed_fbm_render_budget_alignment(app)")
    assert MAIN.index("install_governed_fbm_render_budget_alignment(app)") < MAIN.index("install_governed_fbm_all_orders_health_alignment(app)")


def test_fbm_render_budget_does_not_create_another_read_write_or_refresh_path():
    assert "MarketplaceOrder.query" not in BUDGET
    assert "db.session" not in BUDGET
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
