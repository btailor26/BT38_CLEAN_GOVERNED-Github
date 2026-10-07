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


def test_fbm_final_startup_boundary_strips_feature_assets_and_keeps_actions_lazy():
    source = (ROOT / "services" / "governed_fbm_lazy_startup_alignment.py").read_text(encoding="utf-8")
    for asset in (
        "royal_mail_click_drop_connection.js",
        "fbm_qz_print.js",
        "fbm_tracking_journey.js",
        "fbm_replacement_label_alignment.js",
        "fbm_ebay_shipping_alignment.js",
        "fbm_event_session_refresh_alignment.js",
        "fbm_delivery_promise_journey_alignment.js",
        "fbm_scroll_position_alignment.js",
        "fbm_row_truth_alignment.js",
    ):
        assert asset in source
    assert "target.closest('#royalMailConnectionCard" in source
    assert "target.closest('#qzConnect,#qzSavePrinter" in source
    assert 'provider-action[data-provider="ebay_shipping"]' in source
    assert "target.closest('#readyToShipSelected,.fbm-shipping-options" in source
    assert "window.addEventListener('bt38-marketplace-event'" not in source


def test_lazy_startup_boundary_is_installed_before_feature_injectors():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    lazy = source.index("install_governed_fbm_lazy_startup_alignment(app)")
    replacement = source.index("install_governed_fbm_replacement_label_alignment(app)")
    ebay = source.index("install_governed_ebay_native_shipping_alignment(app)")
    assert lazy < replacement
    assert lazy < ebay


def test_fbm_rows_do_not_flash_before_browser_session_queue_projection():
    source = (ROOT / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")
    assert '.fbm-orders-table:not([data-bt38-session-ready="1"]) tbody tr.fbm-order-row{visibility:hidden}' in source
    assert "table.dataset.bt38SessionReady='1';saveSession();" in source


def test_feature_asset_strip_pattern_matches_real_script_tags():
    import re
    from services.governed_fbm_lazy_startup_alignment import _strip_feature_assets
    html = (
        '<script src="/static/js/fbm_tracking_journey.js?v=1.0.1"></script>'
        '<script src="/static/js/royal_mail_click_drop_connection.js?v=2"></script>'
        '<script src="/static/js/fbm_row_truth_alignment.js"></script>'
    )
    stripped = _strip_feature_assets(html)
    assert "fbm_tracking_journey.js" not in stripped
    assert "royal_mail_click_drop_connection.js" not in stripped
    assert "fbm_row_truth_alignment.js" not in stripped
    assert not re.search(r"<script[^>]+src=", stripped)


def test_tracking_journey_is_lazy_owned_by_tracking_number_click():
    source = (ROOT / "services" / "governed_fbm_lazy_startup_alignment.py").read_text(encoding="utf-8")
    assert "target.closest('.fbm-tracking-journey')" in source
    assert "replayAfter('fbm_tracking_journey.js',event)" in source


def test_silent_refresh_is_db_backed_and_independent_of_tracking_ui():
    source = (ROOT / "services" / "governed_fbm_exact_record_session_alignment.py").read_text(encoding="utf-8")
    assert "async function replaceFromPersistedDb(detail)" in source
    assert "'X-BT38-UI-Refresh':'targeted'" in source
    assert "void replaceFromPersistedDb(detail);" in source
    assert "fbm_tracking_journey.js" not in source


def test_tracking_journey_has_no_duplicate_committed_event_refresh_owner():
    tracking = (ROOT / "static" / "js" / "fbm_tracking_journey.js").read_text(encoding="utf-8")
    exact_owner = (ROOT / "services" / "governed_fbm_exact_record_session_alignment.py").read_text(encoding="utf-8")
    assert "applyCommittedFbmSnapshot" not in tracking
    assert "bt38RefreshExactCommittedFbmRow" not in tracking
    assert "X-BT38-UI-Refresh" not in tracking
    assert "window.addEventListener('bt38-marketplace-event'" not in tracking
    assert "async function replaceFromPersistedDb(detail)" in exact_owner
    assert "'X-BT38-UI-Refresh':'targeted'" in exact_owner


def test_fbm_filters_use_seeded_browser_snapshot_without_history_fetch():
    search = (ROOT / "services" / "governed_fbm_global_search_alignment.py").read_text(encoding="utf-8")
    dispatch = (ROOT / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")
    page = (ROOT / "services" / "governed_fbm_page_alignment.py").read_text(encoding="utf-8")
    assert 'return "1y"' in search
    assert "expandHistoryWorkingSet" not in dispatch
    assert "historyExpansion" not in dispatch
    assert "X-BT38-FBM-History-Expansion" not in dispatch
    assert "function applyHistory()" in dispatch
    assert "refreshHistoryMatches();render();" in dispatch
    assert "bt38-fbm-session-rendered" in dispatch
    assert "Follows History filter" in page
    assert 'onchange="this.form.submit()"' not in page
