from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_base_wires_one_shared_page_refresh_controller():
    base = _read("templates/base.html")
    controller = _read("static/js/bt38-live-page-refresh.js")

    assert "bt38-live-page-refresh.js" in base
    assert "bt38-marketplace-event" in controller
    assert "new EventSource(" not in controller
    assert "setInterval(" not in controller
    assert "setTimeout(" not in controller
    assert "fetch(" not in controller
    assert "window.location.reload()" not in controller


def test_shared_refresh_is_event_driven_deduplicated_and_non_disruptive():
    controller = _read("static/js/bt38-live-page-refresh.js")

    assert "lastSequence" in controller
    assert "document.visibilityState === 'hidden'" in controller
    assert "pendingWhileHidden" in controller
    assert "Never reload or rerender the whole page" in controller


def test_product_linking_reuses_existing_targeted_refresh_for_active_search():
    controller = _read("static/js/bt38-live-page-refresh.js")
    session = _read("static/js/product-linking-session.js")

    assert 'data-bt38-page="productLinking"' in controller
    assert "bt38ProductLinkingFilterForm" in controller
    assert "bt38RefreshProductLinkingRecord" in controller
    assert "warehouseId: detail?.warehouse_stock_id" in controller
    assert "groupId: detail?.group_id" in controller
    assert "listingId: detail?.listing_id" in controller
    assert "listingSku: detail?.seller_sku || search" in controller
    assert "window.bt38RefreshProductLinkingRecord = refreshAffectedRecord" in session
    assert "fetchDataset(" in session


def test_mcf_keeps_its_single_narrow_refresh_without_global_duplicate():
    controller = _read("static/js/bt38-live-page-refresh.js")
    mcf = _read("templates/mcf_orders.html")

    assert "mcf-orders-body" in controller
    assert "pageOwnsCommittedRefresh" in controller
    assert "bt38-marketplace-event" in mcf
    assert "new EventSource(" not in mcf


def test_existing_sse_transport_carries_exact_committed_scope_without_second_transport():
    base = _read("templates/base.html")
    signal = _read("services/governed_ui_event_signal.py")
    controller = _read("static/js/bt38-live-page-refresh.js")

    assert '"/governed/ui/events/stream"' in base
    assert "JSON.parse(event.data" in base
    assert "contract: contract" in base
    assert "json.dumps(contract" in signal
    assert 'contract["sequence"] = current_revision' in signal
    assert "_collapse_events(unseen)" in signal
    assert "new EventSource(" not in controller
    assert "event?.detail || {}" in controller
