from pathlib import Path


def test_fbm_journey_uses_rendered_db_promise_not_provider_payload():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    assert "promiseFromRow(row)" in source
    assert "Marketplace promise · persisted BT38 order" in source
    assert "payload.marketplace_promise" not in source
    assert "performanceBlock(promise, history, payload.provider_status)" in source


def test_fbm_promise_alignment_owns_every_tracking_journey_click():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    # Provider-backed and marketplace-backed journeys must use the same rendered
    # DB promise. A provider button must not fall through to the legacy handler,
    # which can expose a second promise payload and create conflicting dates.
    assert "event.target.closest('.fbm-tracking-journey')" in source
    assert ".fbm-tracking-journey[data-journey-source=\"marketplace\"]" not in source
    assert "event.stopImmediatePropagation()" in source


def test_fbm_journey_alignment_is_loaded_for_the_single_fbm_page():
    source = Path("services/governed_order_clarity_alignment.py").read_text(encoding="utf-8")

    assert 'src="/static/js/fbm_delivery_promise_journey_alignment.js"' in source
    assert "_align_fbm_promise_journey_html" in source
    assert 'path == "/fbm"' in source


def test_fbm_journey_alignment_does_not_add_db_or_marketplace_reads():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    # The only network read retained is the existing, click-scoped Packlink status route.
    assert "/packlink/status" in source
    assert "/api/amazon" not in source
    assert "/api/ebay" not in source
    assert "marketplace_promise" not in source
    assert "setInterval" not in source


def test_fbm_row_promise_status_text_and_colour_share_one_authority():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    assert "function alignPromisePerformance(row)" in source
    assert "promiseCell.querySelector('.fbm-delivery-performance')" in source
    assert "holder.innerHTML = performanceHtml(row)" in source
    assert "bg-success text-white\">On time" in source
    assert "bg-danger text-white\">Late" in source
    assert "alignPromisePerformance(row);" in source


def test_exact_record_event_reapplies_promise_colour_without_page_reload():
    source = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")

    assert "bt38-fbm-committed-snapshot-applied" in source
    assert "if (row) alignRowPerformance(row)" in source
    assert "location.reload" not in source
    assert "setInterval" not in source
