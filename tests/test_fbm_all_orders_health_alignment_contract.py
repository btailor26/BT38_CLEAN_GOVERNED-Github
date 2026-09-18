from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEALTH = (ROOT / "services" / "governed_fbm_all_orders_health_alignment.py").read_text(encoding="utf-8")
SEARCH = (ROOT / "services" / "governed_fbm_global_search_alignment.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_retired_all_orders_health_keeps_history_window_helper_only():
    assert 'request.args.get("fbm_range") or "3d"' in HEALTH
    for key in ('"3d"', '"7d"', '"30d"', '"90d"', '"1y"'):
        assert key in HEALTH
    assert 'mode == "custom"' in HEALTH
    assert "def _selected_history_window()" in HEALTH


def test_all_orders_health_installer_is_compatibility_noop_not_runtime_authority():
    assert "Retired compatibility shim" in HEALTH
    assert "return app" in HEALTH
    assert "db.session.query" not in HEALTH
    assert "page_alignment." not in HEALTH
    assert "global_search." not in HEALTH
    assert "app.view_functions" not in HEALTH
    assert "install_governed_fbm_all_orders_health_alignment(app)" not in MAIN


def test_history_working_set_is_owned_by_global_search_not_visible_pager():
    assert "_RANGE_ROW_CAP = 5000" in SEARCH
    assert "candidate_limit = _RANGE_ROW_CAP + 1" in SEARCH
    assert "requested * _RANGE_CANDIDATE_MULTIPLIER" not in SEARCH
    assert "broad_lookup = bool(_search_term() or _workflow_tab())" not in SEARCH
    assert ".limit(candidate_limit)" in SEARCH


def test_retired_health_helper_remains_read_only():
    assert "requests." not in HEALTH
    assert "db.session.add" not in HEALTH
    assert "db.session.commit" not in HEALTH
    assert "get_or_refresh_amazon_profile" not in HEALTH
