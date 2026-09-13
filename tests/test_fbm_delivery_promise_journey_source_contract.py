from pathlib import Path


def test_fbm_journey_uses_rendered_db_promise_not_provider_payload():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    # Promise and delivery-performance truth are rendered into the FBM row by
    # the governed server path. The click journey must consume that persisted
    # row snapshot rather than asking a marketplace/provider for another truth.
    assert "function promiseHtml(row)" in source
    assert "row?.dataset?.shipByAt" in source
    assert "row?.dataset?.deliveryPromiseAt" in source
    assert "Marketplace promise · persisted BT38 DB" in source
    assert "function performanceHtml(row)" in source
    assert "performanceHtml(row)" in source
    assert "payload.marketplace_promise" not in source
    assert "marketplace_promise" not in source


def test_fbm_promise_alignment_owns_every_tracking_journey_click():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    # One capture-phase selector owns both BT38 journey buttons and preserved
    # marketplace order links, so they cannot fall through to a second promise
    # authority in the legacy handler.
    assert "const TRACKING_TRIGGER_SELECTOR" in source
    assert ".fbm-tracking-journey" in source
    assert 'a[href*="ebay.co.uk/mesh/ord/details"]' in source
    assert 'a[href*="sellercentral.amazon.co.uk/orders-v3/order/"]' in source
    assert "event.target.closest(TRACKING_TRIGGER_SELECTOR)" in source
    assert "event.stopImmediatePropagation()" in source
    assert "window.addEventListener('click', intercept, true)" in source
    assert ".fbm-tracking-journey[data-journey-source=\"marketplace\"]" not in source


def test_fbm_journey_alignment_is_loaded_for_the_single_fbm_page():
    source = Path("services/governed_order_clarity_alignment.py").read_text(encoding="utf-8")

    assert 'src="/static/js/fbm_delivery_promise_journey_alignment.js"' in source
    assert "_align_fbm_promise_journey_html" in source
    assert 'path == "/fbm"' in source


def test_fbm_journey_alignment_does_not_add_db_or_marketplace_reads():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    # Journey opening is presentation-only over the already-rendered persisted
    # row. No Packlink, marketplace, DB/API, polling, or background refresh is
    # allowed from this browser alignment layer.
    assert "fetch(" not in source
    assert "/packlink/status" not in source
    assert "/api/amazon" not in source
    assert "/api/ebay" not in source
    assert "marketplace_promise" not in source
    assert "setInterval" not in source
    assert "setTimeout" not in source
