from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRUTH = (ROOT / "services" / "governed_fbm_data_truth_review.py").read_text(encoding="utf-8")
ROUTE = (ROOT / "services" / "governed_amazon_exact_order_recovery_route.py").read_text(encoding="utf-8")
DISPATCH = (ROOT / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "fbm.html").read_text(encoding="utf-8")


def test_data_truth_review_is_db_only_and_structured():
    assert "external_call_started" in TRUTH
    assert '"db_authority": True' in TRUTH
    for state in ("known", "missing", "unverified", "unavailable", "not_applicable"):
        assert state in TRUTH
    for field in (
        "marketplace",
        "store_name",
        "marketplace_order_id",
        "order_created_at",
        "product_name",
        "sku",
        "quantity",
        "fulfillment_type",
        "tracking_number",
        "carrier",
        "shipping_source",
        "provider_reference",
        "tracking_history",
        "shipping_fee",
        "ship_by_promise",
        "delivery_promise",
    ):
        assert f'"{field}"' in TRUTH


def test_recovery_check_consumes_data_truth_review_instead_of_own_missing_list():
    check = ROUTE.split("def check_exact_marketplace_order_recovery", 1)[1].split(
        "@governed_amazon_exact_order_recovery_bp.post", 1
    )[0]
    assert "review_fbm_data_truth" in check
    assert 'truth_review["recovery_required"]' in check
    assert 'truth_review["missing"]' in check
    assert '"truth_review": truth_review' in check
    assert 'missing.append("Amazon tracking event history")' not in check


def test_fbm_has_one_canonical_shipping_fee_column():
    assert "<th>Shipping fee</th>" in TEMPLATE
    assert "function ensureCostHeader()" not in DISPATCH
    assert "head.insertBefore(th,head.lastElementChild)" not in DISPATCH
    assert "function addCostCell(row,info){{return;}}" in DISPATCH


def test_data_truth_asks_existing_mcf_authority_before_generic_marketplace_truth():
    source = Path("services/governed_fbm_data_truth_review.py").read_text()
    readback = Path("scripts/recover_marketplace_dispatch_history.py").read_text()
    assert '"mcf_order": dict(mcf) if mcf else None' in readback
    assert "FROM mcf_orders" in readback
    assert "source_store_id = :store_id" in readback
    assert "source_order_id = :order_id" in readback
    assert 'shipping_source = "amazon_mcf" if is_mcf else provider' in source
    assert 'source_authority = "mcf_orders" if is_mcf' in source
    assert 'authority="mcf_orders"' in source
    assert 'mcf.get("total_mcf_fee")' in source


def test_marketplace_channel_is_never_presented_as_shipping_source():
    template = Path("templates/fbm.html").read_text()
    page = Path("services/governed_fbm_page_alignment.py").read_text()
    truth = Path("services/governed_fbm_data_truth_review.py").read_text()
    shipping_cell = template.split('<td class="fbm-route-cell">', 1)[1].split("</td>", 1)[0]
    assert "Source unverified" in shipping_cell
    assert "source_label = 'Marketplace'" not in shipping_cell
    assert "shipment.provider != 'marketplace'" in shipping_cell
    assert '"marketplace_shipping": 0' in page
    assert 'provider and provider != "marketplace"' in truth
    assert '_field("unverified", provider or None' in truth


def test_data_truth_review_covers_current_fbm_template_row_facts():
    readback = Path("scripts/recover_marketplace_dispatch_history.py").read_text()
    for field in (
        "marketplace", "store_name", "marketplace_order_id", "order_created_at",
        "product_name", "sku", "quantity", "fulfillment_type",
    ):
        assert f'"{field}"' in TRUTH
        assert f'"{field}"' in readback
    assert 'if fact["state"] in {"missing", "unverified"}' in TRUTH
    assert '"recovery_required": bool(gaps)' in TRUTH


def test_amazon_generic_marketplace_shipment_is_broad_amazon_shipping_source():
    source = DATA_TRUTH.read_text()
    template = TEMPLATE.read_text()
    assert 'amazon_marketplace_source' in source
    assert '"amazon_shipping" if amazon_marketplace_source' in source
    assert "shipment.provider == 'marketplace' and platform_key == 'amazon'" in template
    assert '>Amazon Shipping</span>' in template


def test_journey_summary_uses_persisted_lifecycle_before_scan_history():
    journey = (ROOT / "static/js/fbm_delivery_promise_journey_alignment.js").read_text()
    assert "persistedDelivered" in journey
    assert "persistedDispatched" in journey
    assert "delivered: Boolean(delivered || persistedDelivered)" in journey
    assert "return persistedMilestones(row).delivered;" in journey
    assert "No detailed carrier scan history has been persisted yet." in journey
