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
