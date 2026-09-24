"""Keep the bounded FBM marketplace presentation DB/event-only.

The FBM page must never block on marketplace reads. Amazon/eBay tracking and
lifecycle truth is hydrated by the existing governed event/runtime paths and
persisted before presentation. This adapter only projects already-persisted
Amazon lifecycle state into the existing journey badges and aligns marketplace
tracking clicks to the already-built FBM journey handler. It performs no provider
call, polling, profile refresh, tracking readback, DB write, worker or scan from
the page-render or tracking-click path.
"""
from __future__ import annotations

from markupsafe import escape

import services.governed_fbm_page_alignment as _page_alignment


_original_render_template = _page_alignment.render_template


def _amazon_row(row) -> bool:
    store = getattr(row, "store", None)
    return str(getattr(store, "platform", "") or "").strip().lower() == "amazon"


def _tracking_number(item: dict) -> str:
    shipment = item.get("shipment")
    order = item.get("order")
    value = getattr(shipment, "tracking_number", None) if shipment is not None else None
    if not value and order is not None:
        value = getattr(order, "tracking_number", None)
    return str(value or "").strip()


def _align_persisted_tracking_clicks(html: str, orders: list[dict]) -> str:
    """Point Amazon/eBay tracking at the existing FBM journey modal handler."""
    for item in orders:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or "").strip().lower()
        if platform not in {"amazon", "ebay"}:
            continue
        order = item.get("order")
        tracking = _tracking_number(item)
        marketplace_order_id = str(getattr(order, "marketplace_order_id", "") or "").strip()
        if not tracking or not marketplace_order_id:
            continue

        safe_tracking = str(escape(tracking))
        safe_order_id = str(escape(marketplace_order_id))
        if platform == "amazon":
            old = (
                f'<a href="https://sellercentral.amazon.co.uk/orders-v3/order/{safe_order_id}" '
                f'target="_blank" rel="noopener noreferrer"><code>{safe_tracking}</code></a>'
            )
            platform_label = "Amazon"
        else:
            old = (
                f'<a href="https://www.ebay.co.uk/mesh/ord/details?orderid={safe_order_id}" '
                f'target="_blank" rel="noopener noreferrer"><code>{safe_tracking}</code></a>'
            )
            platform_label = "eBay"
        new = (
            '<button class="btn btn-link btn-sm p-0 align-baseline fbm-tracking-journey" '
            'type="button" data-journey-source="marketplace" '
            f'data-platform="{platform_label}" '
            f'data-marketplace-order-id="{safe_order_id}" '
            f'data-tracking-number="{safe_tracking}" '
            'aria-label="Open BT38 shipment journey">'
            f'<code>{safe_tracking}</code></button>'
        )
        if old in html:
            html = html.replace(old, new, 1)
    return html


def _governed_render_template(template_name, *args, **context):
    rendered = _original_render_template(template_name, *args, **context)
    if template_name == "fbm.html":
        return _align_persisted_tracking_clicks(rendered, context.get("orders") or [])
    return rendered


if not getattr(_page_alignment, "_amazon_marketplace_journey_alignment_installed", False):
    _page_alignment.render_template = _governed_render_template
    _page_alignment._amazon_marketplace_journey_alignment_installed = True
