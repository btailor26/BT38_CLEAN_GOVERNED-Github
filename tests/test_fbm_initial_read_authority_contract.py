from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HISTORY = (ROOT / "services" / "governed_fbm_history_controls_alignment.py").read_text(encoding="utf-8")
SESSION = (ROOT / "services" / "governed_fbm_browser_session_authority_alignment.py").read_text(encoding="utf-8")
PAGE = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text(encoding="utf-8")


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
