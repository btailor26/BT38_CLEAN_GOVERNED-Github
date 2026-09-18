from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text(encoding="utf-8")
SESSION = (ROOT / "services" / "governed_fbm_browser_session_authority_alignment.py").read_text(encoding="utf-8")
HISTORY = (ROOT / "services" / "governed_fbm_all_orders_health_alignment.py").read_text(encoding="utf-8")


def test_health_period_uses_same_selected_history_window_as_fbm_session():
    assert "page._health_summary = _browser_session_health_shell" in SESSION
    assert "health._selected_history_window()" in SESSION
    assert 'request.args.get("fbm_range") or "3d"' in HISTORY
    for key in ('"3d"', '"7d"', '"30d"', '"90d"', '"1y"'):
        assert key in HISTORY
    assert 'mode == "custom"' in HISTORY


def test_health_shell_does_not_create_second_db_or_provider_reader():
    shell = SESSION.split("def _browser_session_health_shell()", 1)[1].split("def _session_health_script", 1)[0]
    assert "db.session.query" not in shell
    assert "requests." not in shell
    assert '"source": "browser_session"' in shell


def test_existing_health_cards_and_shipping_setup_remain_presentation_only():
    for label in ('"Orders"', '"Ready to ship"', '"Dispatched"', '"Returns"', '"Replacements"', '"Refunds / issues"'):
        assert label in PAGE
    assert 'role="tooltip"' in PAGE
    assert 'Shipping setup' in PAGE
    assert 'id="packlinkConnectionTest"' in PAGE
    assert 'id="qzConnect"' in PAGE


def test_legacy_independent_health_period_is_not_runtime_authority():
    assert "page._health_summary = _browser_session_health_shell" in SESSION
    assert 'request.args.get("health_period")' not in SESSION
    assert 'request.args.get("health_date")' not in SESSION
    assert 'request.args.get("health_month")' not in SESSION
