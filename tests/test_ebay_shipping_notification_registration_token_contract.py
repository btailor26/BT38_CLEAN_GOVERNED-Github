from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ebay_notification_registration_does_not_use_fulfillment_only_token():
    source = _read("services/governed_ebay_shipping_notification_registration_alignment.py")

    assert "del access_token" in source
    assert "_shipping_access_token" in source
    assert 'notification_token = str(token_result["access_token"])' in source
    assert "_ORIGINAL(store=store, access_token=notification_token)" in source
    assert "ensure_ebay_shipping_notification_alignment(" in source
    assert "access_token=notification_token" in source


def test_order_readback_token_remains_separate_fulfillment_authority():
    source = _read("services/governed_marketplace_order_import.py")

    assert '"scope": "https://api.ebay.com/oauth/api_scope/sell.fulfillment"' in source
    assert "def _ebay_access_token(store: Store) -> str:" in source


def test_shipping_registration_remains_event_driven_only():
    source = _read("services/governed_ebay_shipping_notification_registration_alignment.py")

    assert "no worker, poller, scheduler" in source
    assert "setInterval" not in source
    assert "while True" not in source
