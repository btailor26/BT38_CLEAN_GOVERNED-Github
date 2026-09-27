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
