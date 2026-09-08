from services import governed_ebay_shipping_notification_alignment as shipping


def test_shipping_access_token_refreshes_exact_persisted_grant(monkeypatch):
    granted = (
        "https://api.ebay.com/oauth/api_scope "
        "https://api.ebay.com/oauth/api_scope/commerce.notification.subscription "
        "https://api.ebay.com/oauth/api_scope/commerce.shipping"
    )
    credentials = {
        "refresh_token": "refresh-token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "oauth_granted_scope": granted,
    }
    monkeypatch.setattr(shipping, "_decode_store_credentials", lambda store: credentials)
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"access_token": "shipping-token"}

    def fake_post(url, *, auth, data, timeout):
        captured.update({"url": url, "auth": auth, "data": data, "timeout": timeout})
        return Response()

    monkeypatch.setattr(shipping.requests, "post", fake_post)

    result = shipping._shipping_access_token(object())

    assert result == {"ok": True, "access_token": "shipping-token"}
    assert captured["data"]["scope"] == granted
    assert "https://api.ebay.com/oauth/api_scope" in captured["data"]["scope"].split()
    assert (
        "https://api.ebay.com/oauth/api_scope/commerce.notification.subscription"
        in captured["data"]["scope"].split()
    )
    assert (
        "https://api.ebay.com/oauth/api_scope/commerce.shipping"
        in captured["data"]["scope"].split()
    )


def test_shipping_subscription_readback_requires_exact_enabled_subscription(monkeypatch):
    monkeypatch.setattr(
        shipping,
        "_get_topic_subscriptions",
        lambda **kwargs: [
            {
                "subscriptionId": "sub-123",
                "topicId": "ITEM_MARKED_SHIPPED",
                "destinationId": "dest-123",
                "status": "ENABLED",
            }
        ],
    )

    result = shipping._shipping_subscription_readback(
        access_token="shipping-token",
        destination_id="dest-123",
        subscription_id="sub-123",
    )

    assert result == {
        "found": True,
        "enabled": True,
        "topic_id": "ITEM_MARKED_SHIPPED",
        "destination_id": "dest-123",
        "status": "ENABLED",
        "topic_matches": True,
        "destination_matches": True,
    }


def test_shipping_subscription_readback_rejects_wrong_destination(monkeypatch):
    monkeypatch.setattr(
        shipping,
        "_get_topic_subscriptions",
        lambda **kwargs: [
            {
                "subscriptionId": "sub-123",
                "topicId": "ITEM_MARKED_SHIPPED",
                "destinationId": "other-destination",
                "status": "ENABLED",
            }
        ],
    )

    result = shipping._shipping_subscription_readback(
        access_token="shipping-token",
        destination_id="dest-123",
        subscription_id="sub-123",
    )

    assert result["found"] is True
    assert result["enabled"] is False
    assert result["destination_matches"] is False
    assert shipping._subscription_readback_reason(result) == (
        "shipping_subscription_destination_mismatch"
    )


def test_shipping_subscription_readback_rejects_disabled_subscription(monkeypatch):
    monkeypatch.setattr(
        shipping,
        "_get_topic_subscriptions",
        lambda **kwargs: [
            {
                "subscriptionId": "sub-123",
                "topicId": "ITEM_MARKED_SHIPPED",
                "destinationId": "dest-123",
                "status": "DISABLED",
            }
        ],
    )

    result = shipping._shipping_subscription_readback(
        access_token="shipping-token",
        destination_id="dest-123",
        subscription_id="sub-123",
    )

    assert result["found"] is True
    assert result["enabled"] is False
    assert shipping._subscription_readback_reason(result) == (
        "shipping_subscription_not_enabled"
    )


def test_shipping_subscription_readback_requires_returned_subscription(monkeypatch):
    monkeypatch.setattr(
        shipping,
        "_get_topic_subscriptions",
        lambda **kwargs: [],
    )

    result = shipping._shipping_subscription_readback(
        access_token="shipping-token",
        destination_id="dest-123",
        subscription_id="sub-123",
    )

    assert result["found"] is False
    assert result["enabled"] is False
    assert shipping._subscription_readback_reason(result) == (
        "shipping_subscription_not_found_after_alignment"
    )
