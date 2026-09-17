from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HISTORY = (ROOT / "services" / "governed_fbm_history_controls_alignment.py").read_text(encoding="utf-8")
SESSION = (ROOT / "services" / "governed_fbm_browser_session_authority_alignment.py").read_text(encoding="utf-8")
PAGE = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text(encoding="utf-8")
DISPATCH = (ROOT / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")
GLOBAL_SEARCH = (ROOT / "services" / "governed_fbm_global_search_alignment.py").read_text(encoding="utf-8")
OLD_HEALTH = (ROOT / "services" / "governed_fbm_all_orders_health_alignment.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_history_does_not_replace_initial_fbm_reader():
    assert "page._latest_distinct_fbm_rows = _selected_rows" not in HISTORY
    assert "controls._session_snapshot_rows()" not in HISTORY
    assert "DO NOT replace" in HISTORY


def test_browser_session_calls_captured_bounded_reader_only():
    assert "return page._bt38_original_bounded_fbm_rows(limit)" in SESSION
    assert "page._latest_distinct_fbm_rows = _bounded_browser_session_rows" in SESSION
    assert "365-day .all()" not in SESSION
    assert "timedelta(days=364)" not in SESSION
    assert "MarketplaceOrder.created_at >= start_at" not in SESSION


def test_health_initial_render_uses_existing_browser_session_facts():
    assert "page._health_summary = _browser_session_health_shell" in SESSION
    assert "def _browser_session_health_shell()" in SESSION
    assert '"source": "browser_session"' in SESSION
    assert "_selected_fbm_rows()" not in SESSION
    assert "db.session.query" not in SESSION
    assert "MarketplaceOrder" not in SESSION
    assert "Object.keys(data).forEach" in SESSION
    assert "bt38-fbm-committed-snapshot-applied" in SESSION


def test_original_page_reader_is_sql_bounded():
    assert "def _latest_distinct_fbm_rows(limit: int)" in PAGE
    assert ".limit(candidate_limit)" in PAGE
    assert "return rows[:limit], has_more" in PAGE


def test_performance_alignment_does_not_touch_print_or_purchase_paths():
    combined = HISTORY + SESSION
    assert "fbm_qz_print" not in combined
    assert "/packlink/draft" not in combined
    assert "/amazon/purchase" not in combined
    assert "qz.print" not in combined
    assert "setInterval(" not in combined
    assert "EventSource(" not in combined


def test_lifecycle_hydration_is_scoped_to_history_window():
    assert "function historyScope()" in DISPATCH
    assert "function lifecycleLoadedKey(name)" in DISPATCH
    assert "'bt38_fbm_loaded_'+historyScope()+'_'+name" in DISPATCH
    assert "var loadedKey=lifecycleLoadedKey(name)" in DISPATCH
    assert "sessionStorage.setItem(lifecycleLoadedKey(legacyTab),'1')" in DISPATCH
    assert "var loadedKey='bt38_fbm_loaded_'+name" not in DISPATCH


def test_explicit_url_history_state_beats_saved_browser_state():
    assert "params.get('fbm_range')||saved.range||'3d'" in DISPATCH
    assert "params.has('fbm_from')" in DISPATCH
    assert "params.has('fbm_to')" in DISPATCH


def test_legacy_whole_session_mutation_api_is_retired():
    assert "BT38FBMApplyCommittedSnapshot" not in DISPATCH


def test_retired_all_orders_health_module_cannot_become_second_authority():
    assert "def install_governed_fbm_all_orders_health_alignment" not in OLD_HEALTH
    assert "db.session.query" not in OLD_HEALTH
    assert "_persisted_workflow_snapshot =" not in OLD_HEALTH
    assert "_health_summary =" not in OLD_HEALTH
    assert "install_governed_fbm_all_orders_health_alignment(app)" not in MAIN
    assert "from services.governed_fbm_all_orders_health_alignment import install_governed_fbm_all_orders_health_alignment" not in MAIN


def test_lifecycle_classifier_is_not_monkey_patched():
    assert "global_search.workflow_queue_for =" not in DISPATCH
    assert "workflow_queue_for = global_search.workflow_queue_for" not in DISPATCH
    assert "return dispatch._aligned_workflow_queue_for(row, shipment)" in GLOBAL_SEARCH
