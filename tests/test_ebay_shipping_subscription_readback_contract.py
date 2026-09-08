from services import governed_ebay_shipping_notification_alignment as shipping


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
