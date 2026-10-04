from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = (ROOT / "services" / "governed_amazon_exact_order_recovery_route.py").read_text()
TEMPLATE = (ROOT / "templates" / "fbm.html").read_text()


def test_exact_amazon_recovery_plans_calls_from_db_truth_gaps():
    section = ROUTE.split('def recover_exact_amazon_order_manually():', 1)[1].split(
        '@governed_amazon_exact_order_recovery_bp.post("/governed/actions/marketplace/dispatch-history-recovery")', 1
    )[0]
    assert "before = _database_readback(store_id, order_id)" in section
    assert "before_review = review_fbm_data_truth" in section
    assert "gaps = set(before_review.get(\"missing\") or []) | set(before_review.get(\"unverified\") or [])" in section
    assert "if gaps & tracking_gaps:" in section
    assert "if gaps & promise_gaps:" in section
    assert "if gaps & label_gaps:" in section


def test_provider_results_only_count_after_fresh_db_read_and_truth_review():
    section = ROUTE.split('def recover_exact_amazon_order_manually():', 1)[1].split(
        '@governed_amazon_exact_order_recovery_bp.post("/governed/actions/marketplace/dispatch-history-recovery")', 1
    )[0]
    assert "db.session.expire_all()" in section
    assert "after = _database_readback(store_id, order_id)" in section
    assert "after_review = review_fbm_data_truth" in section
    assert "persisted_recovered = sorted(gaps - gaps_after)" in section
    assert '"db_authority": True' in section


def test_recovery_ui_verifies_db_after_provider_calls():
    section = TEMPLATE.split("if(recoverButton)recoverButton.addEventListener", 1)[1]
    assert "p.calls_made" in section
    assert "gapsAfter.some(g=>packlinkGaps.has(g))" in section
    assert "exact-order-recovery-check" in section
    assert "DB VERIFIED" in section
    assert "recovered and persisted:" in section


def test_db_gate_requires_one_packlink_history_verification_for_exact_persisted_shipment():
    section = ROUTE.split('def check_exact_marketplace_order_recovery():', 1)[1].split(
        '@governed_amazon_exact_order_recovery_bp.post("/governed/actions/amazon/exact-order-recovery")', 1
    )[0]
    assert "packlink_history_verification_required = bool(" in section
    assert 'shipment_truth.get("provider_shipment_id")' in section
    assert "if packlink_history_verification_required:" in section
    assert "recovery_required = True" in section


def test_exact_packlink_manual_recovery_verifies_history_even_when_db_fields_look_complete():
    section = ROUTE.split('def recover_exact_amazon_order_manually():', 1)[1].split(
        '@governed_amazon_exact_order_recovery_bp.post("/governed/actions/marketplace/dispatch-history-recovery")', 1
    )[0]
    packlink = section.split('if shipping_source == "packlink":', 1)[1].split(
        "calls_started = []", 1
    )[0]
    assert 'calls_started.append("packlink_tracking")' in packlink
    assert "adapter.get_tracking_status(reference=provider_reference)" in packlink
    assert "reconcile_packlink_tracking_lifecycle(" in packlink
    assert "poll" not in packlink.lower()
