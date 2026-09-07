from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ebay_return_topic_uses_existing_governed_registration_path():
    source = (ROOT / "services" / "governed_ebay_notification_registration.py").read_text()

    assert 'RETURN_TOPIC_ID = "ORDER_RETURN_ACTIVITY"' in source
    assert "RETURN_TOPIC_ID," in source.split("REQUIRED_TOPIC_IDS = (", 1)[1].split(")", 1)[0]
    assert "topic_id=RETURN_TOPIC_ID" in source
    assert "_ensure_subscription(" in source
    assert "_topic_schema_version(" in source
    assert 'RETURN_READ_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.return.read"' in source
    assert 'RETURN_WRITE_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.return"' in source


def test_ebay_return_webhook_remains_existing_non_stock_lifecycle_event():
    source = (ROOT / "services" / "governed_webhook_execution.py").read_text()

    assert '("return", ["return", "return request", "refund requested"])' in source
    assert '"return": "Return notification stored for awareness."' in source
    assert 'return _classify_business_event(event_type, payload) == "stock_decrement"' in source
    assert '"return_stored"' in source


def test_optional_notification_scope_failure_does_not_poison_core_ebay_auth():
    source = (ROOT / "services" / "governed_ebay_notification_registration.py").read_text()

    assert 'core_registration_ok = bool(order_subscription_id)' in source
    assert 'overall_ok = core_registration_ok' in source
    assert 'optional_reauthorization_required' in source
    assert 'listing_reauthorization_required' in source
    assert 'return_reauthorization_required' in source


def test_shipping_notification_consent_is_persisted_separately_from_store_auth():
    source = (ROOT / "services" / "governed_ebay_shipping_notification_alignment.py").read_text()

    assert '"ebay_shipping_notification_status"' in source
    assert '"ebay_shipping_notification_reauthorization_required"' in source
    assert '"ebay_shipping_notification_reason"' in source
    assert '"ebay_shipping_notification_attempted_at"' in source
    assert 'store.auth_status' not in source
    assert 'store.auth_error_code' not in source
    assert 'required=False' in source
    assert 'enabled=True' in source
