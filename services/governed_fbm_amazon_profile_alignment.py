"""Keep the bounded FBM Amazon presentation DB/event-only.

The FBM page must never block on Amazon marketplace reads. Amazon order/profile,
tracking and lifecycle truth is hydrated by the existing governed event/runtime
paths and persisted before presentation. This adapter only projects already-
persisted Amazon lifecycle state into the existing journey badges when no real
BT38 shipment exists. It performs no provider call, polling, profile refresh,
tracking readback, DB write, worker or scan from the page-render path.
"""
from __future__ import annotations

import services.governed_fbm_page_alignment as _page_alignment


_original_render_template = _page_alignment.render_template


def _amazon_row(row) -> bool:
    store = getattr(row, "store", None)
    return str(getattr(store, "platform", "") or "").strip().lower() == "amazon"


def _amazon_marketplace_journey_state(order):
    if order is None or not _amazon_row(order):
        return None
    status = (
        str(getattr(order, "status", "") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    # Only persisted post-dispatch lifecycle evidence lights a journey milestone.
    # Amazon "shipped" alone remains dispatch truth with milestones unavailable.
    return {
        "picked_up": "accepted",
        "pickedup": "accepted",
        "accepted": "accepted",
        "carrier_accepted": "accepted",
        "collected": "accepted",
        "in_transit": "in_transit",
        "intransit": "in_transit",
        "out_for_delivery": "out_for_delivery",
        "outfordelivery": "out_for_delivery",
        "delivered": "delivered",
    }.get(status)


def _governed_render_template(template_name, *args, **context):
    if template_name == "fbm.html":
        original_orders = context.get("orders") or []
        aligned_orders = []
        changed = False
        for item in original_orders:
            if not isinstance(item, dict) or item.get("shipment") is not None:
                aligned_orders.append(item)
                continue
            journey_state = _amazon_marketplace_journey_state(item.get("order"))
            if not journey_state:
                aligned_orders.append(item)
                continue
            aligned = dict(item)
            aligned["shipment_state"] = journey_state
            aligned_orders.append(aligned)
            changed = True
        if changed:
            context = dict(context)
            context["orders"] = aligned_orders
    return _original_render_template(template_name, *args, **context)


if not getattr(_page_alignment, "_amazon_marketplace_journey_alignment_installed", False):
    _page_alignment.render_template = _governed_render_template
    _page_alignment._amazon_marketplace_journey_alignment_installed = True
