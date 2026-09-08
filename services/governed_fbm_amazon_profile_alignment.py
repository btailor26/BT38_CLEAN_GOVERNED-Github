"""Keep the bounded FBM marketplace presentation DB/event-only.

The FBM page must never block on marketplace reads. Amazon/eBay tracking and
lifecycle truth is hydrated by the existing governed event/runtime paths and
persisted before presentation. This adapter only projects already-persisted
Amazon lifecycle state into the existing journey badges and aligns marketplace
tracking clicks to those already-rendered journey badges. It performs no provider
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


def _tracking_number(item: dict) -> str:
    shipment = item.get("shipment")
    order = item.get("order")
    value = getattr(shipment, "tracking_number", None) if shipment is not None else None
    if not value and order is not None:
        value = getattr(order, "tracking_number", None)
    return str(value or "").strip()


def _align_persisted_tracking_clicks(html: str, orders: list[dict]) -> str:
    """Point Amazon/eBay tracking clicks at the journey already rendered in-row.

    This is deliberately client-only: no network request, XHR, DB endpoint or
    marketplace redirect is installed. The click simply focuses the existing
    .fbm-journey-steps for that row, which was already built from persisted page data.
    """
    changed = False
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
        else:
            old = (
                f'<a href="https://www.ebay.co.uk/mesh/ord/details?orderid={safe_order_id}" '
                f'target="_blank" rel="noopener noreferrer"><code>{safe_tracking}</code></a>'
            )
        new = (
            '<button class="btn btn-link btn-sm p-0 align-baseline '
            'bt38-persisted-journey" type="button" '
            f'data-marketplace-order-id="{safe_order_id}" '
            f'data-tracking-number="{safe_tracking}" '
            'aria-label="Show persisted BT38 shipment journey">'
            f'<code>{safe_tracking}</code></button>'
        )
        if old in html:
            html = html.replace(old, new, 1)
            changed = True

    if not changed or 'id="bt38PersistedJourneyClickAlignment"' in html:
        return html

    client_only = '''
<style id="bt38PersistedJourneyClickAlignment">
.bt38-persisted-journey,.bt38-persisted-journey:hover,.bt38-persisted-journey:focus{text-decoration:none!important}.fbm-journey-steps.bt38-journey-focus{outline:2px solid rgba(13,110,253,.35);outline-offset:3px;border-radius:4px}
</style>
<script id="bt38PersistedJourneyClickAlignmentScript">
document.addEventListener('click',function(event){const button=event.target.closest('.bt38-persisted-journey');if(!button)return;event.preventDefault();event.stopPropagation();const row=button.closest('.fbm-order-row');const journey=row?row.querySelector('.fbm-journey-steps'):null;if(!journey)return;journey.scrollIntoView({behavior:'smooth',block:'nearest',inline:'nearest'});journey.classList.add('bt38-journey-focus');window.setTimeout(()=>journey.classList.remove('bt38-journey-focus'),1200);});
</script>
'''
    if "</body>" in html:
        return html.replace("</body>", client_only + "</body>", 1)
    return html + client_only


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
        rendered = _original_render_template(template_name, *args, **context)
        return _align_persisted_tracking_clicks(rendered, context.get("orders") or [])
    return _original_render_template(template_name, *args, **context)


if not getattr(_page_alignment, "_amazon_marketplace_journey_alignment_installed", False):
    _page_alignment.render_template = _governed_render_template
    _page_alignment._amazon_marketplace_journey_alignment_installed = True
