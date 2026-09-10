from services.governed_fbm_logical_bell_alignment import _collapse_logical_bell_records


def _sale(*, event_key, created_at, status="unshipped"):
    return {
        "event_key": event_key,
        "log_type": "marketplace_sale",
        "platform": "ebay",
        "title": "Sale · Bio Mystery Retinol Pro Night Cream 30 Gram 0.1%",
        "sku": "EB-CR-RP-NT-30g",
        "quantity": 1,
        "order_id": "06-15157-80792",
        "lifecycle_status": status,
        "created_at": created_at,
    }


def test_ebay_retries_collapse_to_one_ready_to_dispatch_presentation():
    records = [
        _sale(event_key="retry:4", created_at="2026-09-10T19:28:23Z"),
        _sale(event_key="retry:3", created_at="2026-09-10T19:22:36Z"),
        _sale(event_key="retry:2", created_at="2026-09-10T19:16:49Z"),
        _sale(event_key="retry:1", created_at="2026-09-10T19:14:48Z"),
    ]

    result = _collapse_logical_bell_records(records, 20)

    assert len(result) == 1
    assert result[0]["event_key"] == "fbm-ready:ebay:06-15157-80792"
    assert result[0]["title"] == (
        "Get ready to dispatch · eBay · "
        "Bio Mystery Retinol Pro Night Cream 30 Gram 0.1%"
    )
    assert result[0]["created_at"] == "2026-09-10T19:14:48Z"
    assert result[0]["presentation_source"] == "existing_fbm_order_state"


def test_dispatch_and_in_transit_do_not_create_new_bell_items():
    records = [
        _sale(event_key="order:967", created_at="2026-09-10T19:14:48Z"),
        {
            "event_key": "dispatch:967",
            "log_type": "fbm_marketplace_dispatch_confirmed",
            "platform": "ebay",
            "order_id": "06-15157-80792",
            "lifecycle_status": "shipped",
            "created_at": "2026-09-10T20:00:00Z",
        },
        {
            "event_key": "transit:967",
            "log_type": "fbm_in_transit",
            "platform": "ebay",
            "order_id": "06-15157-80792",
            "lifecycle_status": "in_transit",
            "created_at": "2026-09-11T08:00:00Z",
        },
    ]

    result = _collapse_logical_bell_records(records, 20)

    assert len(result) == 1
    assert result[0]["event_key"] == "fbm-ready:ebay:06-15157-80792"
    assert result[0]["title"].startswith("Get ready to dispatch · eBay ·")


def test_delivered_replaces_ready_to_dispatch_item():
    records = [
        _sale(event_key="order:967", created_at="2026-09-10T19:14:48Z"),
        {
            "event_key": "delivered:967",
            "log_type": "fbm_delivered",
            "platform": "ebay",
            "title": "Delivered",
            "order_id": "06-15157-80792",
            "lifecycle_status": "delivered",
            "created_at": "2026-09-12T09:30:00Z",
        },
    ]

    result = _collapse_logical_bell_records(records, 20)

    assert len(result) == 1
    assert result[0]["log_type"] == "fbm_delivered"
    assert result[0]["lifecycle_status"] == "delivered"


def test_non_final_shipping_milestones_are_not_bell_content():
    records = [
        {
            "event_key": "accepted:967",
            "log_type": "fbm_carrier_accepted",
            "platform": "ebay",
            "order_id": "06-15157-80792",
            "lifecycle_status": "carrier_accepted",
            "created_at": "2026-09-11T07:00:00Z",
        },
        {
            "event_key": "out:967",
            "log_type": "marketplace_webhook",
            "platform": "ebay",
            "order_id": "06-15157-80792",
            "lifecycle_status": "out_for_delivery",
            "created_at": "2026-09-12T07:00:00Z",
        },
    ]

    assert _collapse_logical_bell_records(records, 20) == []
