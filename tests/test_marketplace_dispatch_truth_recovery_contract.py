from pathlib import Path


RECOVERY_PATH = Path("scripts/recover_marketplace_dispatch_history.py")
RECOVERY = RECOVERY_PATH.read_text(encoding="utf-8")
RECOVERY_WORKFLOW = Path(
    ".github/workflows/recover-marketplace-dispatch-history.yml"
).read_text(encoding="utf-8")
RECOVERY_ROUTE = Path(
    "services/governed_amazon_exact_order_recovery_route.py"
).read_text(encoding="utf-8")
AMAZON_TRACKING = Path(
    "services/governed_amazon_tracking_readback.py"
).read_text(encoding="utf-8")
DEPLOY = Path(".github/workflows/deploy-fly.yml").read_text(encoding="utf-8")


def test_operator_dispatch_recovery_reuses_exact_existing_authorities():
    assert RECOVERY_PATH.exists()
    assert "hydrate_amazon_tracking_for_order" in RECOVERY
    assert "hydrate_amazon_purchased_label_for_order" in RECOVERY
    assert "hydrate_exact_ebay_order" in RECOVERY
    assert "MarketplaceOrder" in RECOVERY
    assert "Store" in RECOVERY


def test_recovery_covers_db_dispatch_history_without_arbitrary_time_window():
    assert "def _first_dispatch_at(" in RECOVERY
    assert "func.min(" in RECOVERY
    assert "MarketplaceOrder.shipped_at" in RECOVERY
    assert "MarketplaceOrder.updated_at" in RECOVERY
    assert "MarketplaceOrder.created_at" in RECOVERY
    assert "def _candidate_order_ids(" in RECOVERY
    assert "tracking_number.is_(None)" in RECOVERY
    assert "carrier.is_(None)" in RECOVERY

    forbidden_time_caps = (
        "max_days",
        "max_age_hours",
        "timedelta(",
        "INTERVAL '",
        ".limit(",
    )
    for token in forbidden_time_caps:
        assert token not in RECOVERY


def test_recovery_is_finite_operator_action_not_runtime_polling():
    assert '"operator_action": True' in RECOVERY
    assert '"automatic_startup_recovery": False' in RECOVERY
    assert '"polling_started": False' in RECOVERY
    assert '"scheduler_started": False' in RECOVERY
    assert '"worker_started": False' in RECOVERY
    assert '"marketplace_write_started": False' in RECOVERY

    forbidden_runtime = (
        "threading",
        "Thread(",
        "while True",
        "time.sleep",
        "schedule.",
        "APScheduler",
    )
    for token in forbidden_runtime:
        assert token not in RECOVERY


def test_recovery_classifies_from_durable_db_readback_and_keeps_fallback_success():
    assert 'if resolved:' in RECOVERY
    assert 'elif not result.get("success"):' in RECOVERY
    assert 'shipping_label is not None and shipping_label.get("success")' in RECOVERY
    assert '"database_readback": readback' in RECOVERY


def test_operator_route_returns_failure_and_unresolved_evidence():
    assert '"failures": failures' in RECOVERY_ROUTE
    assert '"unresolved": unresolved' in RECOVERY_ROUTE
    assert '"result": order.get("result")' in RECOVERY_ROUTE
    assert '"database_readback": order.get("database_readback")' in RECOVERY_ROUTE
    assert '"automatic_startup_recovery": False' in RECOVERY_ROUTE
    assert '"polling_started": False' in RECOVERY_ROUTE
    assert '"marketplace_write_started": False' in RECOVERY_ROUTE


def test_amazon_v2026_fulfillment_status_is_dispatch_authority():
    assert "def _order_fulfillment_status(" in AMAZON_TRACKING
    assert 'fulfillment = order_payload.get("fulfillment")' in AMAZON_TRACKING
    assert 'fulfillment.get("status")' in AMAZON_TRACKING
    assert "_order_fulfillment_status(order_payload)" in AMAZON_TRACKING
    assert '"SHIPPED": "shipped"' in AMAZON_TRACKING
    assert '"DELIVERED": "delivered"' in AMAZON_TRACKING
    assert '"order_status": _order_fulfillment_status(order_payload)' in AMAZON_TRACKING


def test_governed_deploy_still_does_not_run_recovery_implicitly():
    assert "scripts/recover_marketplace_dispatch_history.py" not in DEPLOY
    assert "recover_missing_dispatch_truth_from_db_start" not in DEPLOY
    assert "Recover stale marketplace dispatch truth once" not in DEPLOY


def test_historical_recovery_requires_explicit_manual_workflow_dispatch():
    assert "workflow_dispatch:" in RECOVERY_WORKFLOW
    assert "RECOVER_DB_DISPATCH_HISTORY" in RECOVERY_WORKFLOW
    assert "expected_commit" in RECOVERY_WORKFLOW
    assert 'test "${{ github.ref_name }}" = "fix/full-system-release-alignment"' in RECOVERY_WORKFLOW
    assert "pulls/528" in RECOVERY_WORKFLOW
    assert "scripts/recover_marketplace_dispatch_history.py" in RECOVERY_WORKFLOW
    assert "Verify deployed recovery source is exact" in RECOVERY_WORKFLOW
    assert "Recover missing Amazon and eBay dispatch truth from DB start" in RECOVERY_WORKFLOW
    assert "schedule:" not in RECOVERY_WORKFLOW
