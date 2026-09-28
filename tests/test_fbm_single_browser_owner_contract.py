from pathlib import Path


DISPATCH = Path("services/governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")
SMALL = Path("services/governed_fbm_small_alignment.py").read_text(encoding="utf-8")


def test_one_fbm_row_visibility_owner():
    assert "function enforceActiveQueue" not in SMALL
    assert "row.style.display='none'" not in SMALL
    assert "queueMicrotask(enforceActiveQueue)" not in SMALL
    assert "window.addEventListener('load',enforceActiveQueue" not in SMALL
    assert "function render()" in DISPATCH
    assert "renderExistingPager(matched)" in DISPATCH


def test_history_expansion_reuses_canonical_shipping_cost_alignment():
    assert "addCostCell(row,info)" not in DISPATCH
    assert DISPATCH.count("alignCanonicalShippingCost(row,info)") >= 2


def test_duplicate_shipping_fee_filter_is_retired():
    assert "data-fbm-shipping-fees" not in DISPATCH
    assert "shipping_fee_missing" not in DISPATCH
    assert "Shipping fee missing" not in DISPATCH


def test_legacy_lifecycle_browser_state_is_retired():
    assert "legacyTab" not in DISPATCH
    assert "legacySearch" not in DISPATCH
    assert "lifecycleLoadedKey" not in DISPATCH
    assert "bt38_fbm_loaded_" not in DISPATCH
    assert "bt38-fbm-session-rendered" not in DISPATCH


def test_lifecycle_filters_remain_browser_session_only():
    assert "window.BT38FBMApplyCommittedSnapshot=render" in DISPATCH
    assert "button.addEventListener('click',function(){{active=name;currentPage=1;saveSession();render()}})" in DISPATCH
    assert "setInterval(" not in DISPATCH
    assert "X-BT38-FBM-History-Expansion" in DISPATCH


def test_tab_render_reuses_committed_history_classification():
    assert "function refreshHistoryMatches()" in DISPATCH
    render_body = DISPATCH.split("function render(){{", 1)[1].split("// Keep the established single FBM browser-session owner", 1)[0]
    assert "inHistory(row)" not in render_body
    assert "refreshHistoryMatches();render();return;" in DISPATCH
    assert "refreshHistoryMatches();document.dispatchEvent" in DISPATCH


def test_history_expansion_renders_complete_bounded_working_set():
    page = Path("services/governed_fbm_page_alignment.py").read_text(encoding="utf-8")
    assert 'request.headers.get("X-BT38-FBM-History-Expansion") == "1"' in page
    assert "rows, has_more = global_search._session_snapshot_rows()" in page
    assert "rows, has_more = _latest_distinct_fbm_rows(visible_limit)" in page


def test_lifecycle_tab_render_uses_cached_browser_snapshot():
    assert "var cachedCounts=" in DISPATCH
    assert "var cachedTruthCounts=" in DISPATCH
    assert "var cachedRowsByQueue=" in DISPATCH
    assert "var queueRows=cachedRowsByQueue[active]||[]" in DISPATCH
    assert "function localCounts(){{return cachedCounts;}}" in DISPATCH
    render_body = DISPATCH.split("function render(){{", 1)[1].split("// Keep the established single FBM browser-session owner", 1)[0]
    assert "rows.filter(function(row)" not in render_body
    assert "if(!inHistory(row))return" not in render_body


def test_history_expansion_returns_rows_not_full_fbm_page():
    page = Path("services/governed_fbm_page_alignment.py").read_text(encoding="utf-8")
    fragment = Path("templates/_fbm_history_rows.html").read_text(encoding="utf-8")
    assert 'request.headers.get("X-BT38-FBM-History-Expansion") == "1"' in page
    assert 'return render_template("_fbm_history_rows.html", orders=orders)' in page
    assert 'extends "base.html"' not in fragment
    assert 'class="fbm-order-row"' in fragment
    assert 'fbm-orders-table' in fragment
