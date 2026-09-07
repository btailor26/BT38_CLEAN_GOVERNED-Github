from services.governed_fbm_logical_action_count_alignment import _collapse_logical_actions


def test_progressed_order_retires_all_stale_ready_siblings():
    records = [
        {
            "platform": "eBay",
            "order_id": "19-15116-57232",
            "sku": "EB-OD-CR-50g-X3",
            "status_label": "Get ready to dispatch",
            "requires_action": True,
        },
        {
            "platform": "eBay",
            "order_id": "19-15116-57232",
            "sku": "EB-OD-CR-100g-X3",
            "status_label": "Get ready to dispatch",
            "requires_action": True,
        },
        {
            "platform": "eBay",
            "order_id": "19-15116-57232",
            "status_label": "In transit",
            "requires_action": False,
        },
        {
            "platform": "Amazon",
            "order_id": "204-6773401-3069916",
            "status_label": "Get ready to dispatch",
            "requires_action": True,
        },
        {
            "platform": "eBay",
            "order_id": "27-15097-79712",
            "status_label": "Get ready to dispatch",
            "requires_action": True,
        },
    ]

    collapsed = _collapse_logical_actions(records)

    actions = [record for record in collapsed if record.get("requires_action") is True]
    assert [(record["platform"], record["order_id"]) for record in actions] == [
        ("Amazon", "204-6773401-3069916"),
        ("eBay", "27-15097-79712"),
    ]
    assert any(
        record.get("order_id") == "19-15116-57232"
        and record.get("status_label") == "In transit"
        for record in collapsed
    )


def test_ready_siblings_without_progress_count_once_per_logical_order():
    records = [
        {
            "platform": "eBay",
            "order_id": "27-15097-79712",
            "sku": "A",
            "status_label": "Get ready to dispatch",
            "requires_action": True,
        },
        {
            "platform": "eBay",
            "order_id": "27-15097-79712",
            "sku": "B",
            "status_label": "Get ready to dispatch",
            "requires_action": True,
        },
    ]

    collapsed = _collapse_logical_actions(records)
    assert sum(record.get("requires_action") is True for record in collapsed) == 1
