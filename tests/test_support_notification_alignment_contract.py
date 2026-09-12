from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUPPORT = (ROOT / "services" / "support_notification_alignment.py").read_text(encoding="utf-8")
ACTIONS = (ROOT / "services" / "governed_action_count_ui_alignment.py").read_text(encoding="utf-8")
INIT = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")


def test_support_notifications_reuse_existing_bell_and_case_authority():
    assert 'endpoint = "governed.governed_ui_notifications"' in SUPPORT
    assert "SupportCase" in SUPPORT
    assert "SupportCaseMessage" in SUPPORT
    assert "support_attention_count" in SUPPORT
    assert "app.view_functions[endpoint] = support_aligned_notifications" in SUPPORT
    assert "import services.support_notification_alignment" in INIT


def test_support_bell_install_is_safe_before_governed_blueprint_registration():
    # services is imported during extension startup, before governed_routes may
    # have registered its endpoint. That ordering must never crash Gunicorn.
    assert 'if original is None:\n        return False' in SUPPORT
    assert 'raise RuntimeError("governed notification endpoint is not registered")' not in SUPPORT
    assert "def _install_when_ready() -> None:" in SUPPORT
    assert "@app.before_request" in SUPPORT
    assert "_bt38_support_notification_install_deferred" in SUPPORT
    assert "_install_when_ready()" in SUPPORT


def test_customer_support_notifications_are_account_scoped():
    assert "_account_for_user(current_user.id)" in SUPPORT
    assert "query = query.filter_by(account_id=account.id)" in SUPPORT
    assert 'str(getattr(current_user, "role", "")).strip().lower() == "admin"' in SUPPORT


def test_reply_attention_is_derived_from_existing_case_conversation():
    assert 'latest_role == "customer"' in SUPPORT
    assert 'latest_role != "admin"' in SUPPORT
    assert 'title = "Customer replied"' in SUPPORT
    assert 'title = "BT38 Support replied"' in SUPPORT
    assert '_ACTIVE_STATES = {"open", "in_progress", "waiting_customer"}' in SUPPORT


def test_bell_payload_contains_safe_case_metadata_not_support_content():
    assert '"case_id": case_id' in SUPPORT
    assert '"case_status": status' in SUPPORT
    assert '"priority": priority' in SUPPORT
    assert '"url": f"/support/cases/{case_id}"' in SUPPORT
    assert 'latest.body' not in SUPPORT
    assert 'case.description' not in SUPPORT
    assert 'context_json' not in SUPPORT


def test_support_notification_layer_has_no_external_or_marketplace_execution_path():
    for forbidden in (
        "requests.",
        "amazon_client",
        "ebay_client",
        "configured_revolut_client",
        "MarketplaceOrder",
        "WarehouseStock",
        "push_quantity",
        "propagate_quantity",
        "setInterval(",
    ):
        assert forbidden not in SUPPORT


def test_badge_combines_support_attention_but_assistant_keeps_marketplace_count():
    assert "var currentSupportCount=0;" in ACTIONS
    assert "var value=marketplaceValue+supportValue;" in ACTIONS
    assert "applyCurrentCounts(payload.action_count,payload.support_attention_count||0);" in ACTIONS
    assert "var expected=normalAssistantMessage(currentCount);" in ACTIONS
    assert "support_count:currentSupportCount" in ACTIONS
