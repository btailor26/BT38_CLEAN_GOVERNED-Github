"""Show existing Amazon MCF lifecycle in its own FBM-workspace area.

This is presentation-only. It reuses the existing /fbm table and persisted
MCFOrder + MarketplaceOrder truth. It introduces no marketplace read, worker,
poller, inventory mutation, shipping action, or second order system.
"""
from __future__ import annotations

from html import escape

from sqlalchemy.orm import joinedload

from extensions import db
from models import MCFOrder, MarketplaceOrder
from services import governed_fbm_dispatch_queue_alignment as dispatch_queue
from services import governed_fbm_fba_visibility_alignment as fba_visibility


_MAX_MCF_ROWS = 300


def _text(value) -> str:
    return str(value or "").strip()


def _is_mcf_marketplace_row(row: MarketplaceOrder) -> bool:
    """Positive persisted MCF identity; never infer MCF from generic FBA alone."""
    if getattr(row, "mcf_order_id", None) is not None:
        return True
    item_id = _text(getattr(row, "marketplace_order_item_id", None)).upper()
    return item_id.startswith("MCF-")


def _canonical_mcf_pairs() -> list[tuple[MCFOrder, MarketplaceOrder]]:
    """Return one existing source MarketplaceOrder row per persisted MCF order."""
    mcf_rows = (
        db.session.query(MCFOrder)
        .order_by(MCFOrder.id.desc())
        .limit(_MAX_MCF_ROWS)
        .all()
    )
    if not mcf_rows:
        return []

    mcf_ids = [int(row.id) for row in mcf_rows if getattr(row, "id", None)]
    source_rows = (
        db.session.query(MarketplaceOrder)
        .filter(MarketplaceOrder.mcf_order_id.in_(mcf_ids))
        .options(joinedload(MarketplaceOrder.store), joinedload(MarketplaceOrder.warehouse_stock))
        .order_by(MarketplaceOrder.id.desc())
        .all()
    )

    latest_source: dict[int, MarketplaceOrder] = {}
    for row in source_rows:
        mcf_id = getattr(row, "mcf_order_id", None)
        if mcf_id is not None and int(mcf_id) not in latest_source:
            latest_source[int(mcf_id)] = row

    return [
        (mcf, latest_source[int(mcf.id)])
        for mcf in mcf_rows
        if int(mcf.id) in latest_source
    ]


def _date_text(mcf: MCFOrder, source: MarketplaceOrder) -> str:
    value = (
        getattr(source, "marketplace_created_at", None)
        or getattr(mcf, "created_at", None)
        or getattr(source, "created_at", None)
    )
    return value.strftime("%d/%m/%Y %H:%M") if value else "—"


def _platform(source: MarketplaceOrder, mcf: MCFOrder) -> str:
    store = getattr(source, "store", None)
    return _text(
        getattr(store, "platform", None)
        or getattr(mcf, "source_channel", None)
        or "marketplace"
    ).lower()


def _platform_label(source: MarketplaceOrder, mcf: MCFOrder) -> str:
    value = _platform(source, mcf)
    return "eBay" if "ebay" in value else ("Amazon" if "amazon" in value else value.title())


def _platform_logo(source: MarketplaceOrder, mcf: MCFOrder) -> str:
    value = _platform(source, mcf)
    if "ebay" in value:
        return "/static/img/marketplaces/ebay.png"
    if "amazon" in value:
        return "/static/img/marketplaces/amazon.png"
    return ""


def _row_html(mcf: MCFOrder, source: MarketplaceOrder) -> str:
    warehouse = getattr(source, "warehouse_stock", None)
    store = getattr(source, "store", None)
    product = _text(getattr(warehouse, "product_name", None) or getattr(source, "sku", None) or "—")
    sku = _text(getattr(source, "sku", None) or "—")
    store_name = _text(getattr(store, "name", None) or _platform_label(source, mcf))
    source_order_id = _text(getattr(mcf, "source_order_id", None) or getattr(source, "marketplace_order_id", None) or "—")
    amazon_order_id = _text(getattr(mcf, "amazon_order_id", None))
    seller_fulfillment_id = _text(getattr(mcf, "seller_fulfillment_order_id", None))
    status = _text(getattr(mcf, "amazon_status", None) or getattr(mcf, "status", None) or "pending")
    carrier = _text(getattr(mcf, "carrier", None))
    tracking = _text(getattr(mcf, "tracking_number", None))
    logo = _platform_logo(source, mcf)
    platform_label = _platform_label(source, mcf)

    try:
        quantity = max(1, int(getattr(source, "quantity", 1) or 1))
    except (TypeError, ValueError):
        quantity = 1

    marketplace_cell = (
        f'<img class="fbm-marketplace-logo" src="{escape(logo, quote=True)}" alt="{escape(platform_label)}" title="{escape(platform_label)}">'
        if logo else f'<strong>{escape(platform_label)}</strong>'
    )
    amazon_line = f'<div class="small text-muted">Amazon {escape(amazon_order_id)}</div>' if amazon_order_id else '<div class="small text-muted">Amazon order ID pending</div>'
    seller_line = f'<div class="small text-muted">{escape(seller_fulfillment_id)}</div>' if seller_fulfillment_id else ""
    shipment = " · ".join(value for value in (carrier, tracking) if value) or "Amazon fulfilment in progress"

    return (
        f'<tr class="fbm-order-row" data-order-id="{int(source.id)}" data-fbm-mcf-readonly="1" '
        f'data-lifecycle-status="{escape(status.lower(), quote=True)}">'
        '<td class="text-center" data-no-row-click="1"><span class="text-muted">—</span></td>'
        f'<td class="fbm-marketplace-cell">{marketplace_cell}<div class="small text-muted mt-1">{escape(store_name)}</div>'
        '<span class="badge bg-light text-dark border mt-1">MCF</span></td>'
        f'<td><span class="fw-semibold">{escape(source_order_id)}</span><div class="small text-muted">{escape(_date_text(mcf, source))}</div>{amazon_line}</td>'
        f'<td class="fbm-product-cell"><strong>{escape(product)}</strong><div class="small text-muted"><code>{escape(sku)}</code></div>{seller_line}</td>'
        f'<td>{quantity}</td>'
        '<td class="fbm-route-cell"><strong>Amazon MCF</strong><div class="small text-muted mt-1">Fulfilled by Amazon · Read only</div></td>'
        '<td class="fbm-promise-cell"><div class="small text-muted">Amazon managed</div></td>'
        f'<td><strong>{escape(shipment)}</strong></td>'
        f'<td><span class="badge bg-light text-dark border">{escape(status.replace("_", " ").title())}</span></td>'
        '<td class="fbm-action-cell" data-no-row-click="1"><span class="badge bg-light text-dark border">Read only</span></td>'
        '</tr>'
    )


def _insert_mcf_rows(html: str, pairs: list[tuple[MCFOrder, MarketplaceOrder]]) -> tuple[str, dict[str, dict], int]:
    table_marker = 'class="table table-hover align-middle mb-0 fbm-orders-table"'
    table_index = html.find(table_marker)
    if table_index < 0:
        return html, {}, 0
    tbody_start = html.find("<tbody>", table_index)
    tbody_end = html.find("</tbody>", tbody_start)
    if tbody_start < 0 or tbody_end < 0:
        return html, {}, 0

    fragments: list[str] = []
    payload: dict[str, dict] = {}
    for mcf, source in pairs:
        row_id = str(int(source.id))
        payload[row_id] = {
            "queue": "mcf",
            "status": _text(getattr(mcf, "amazon_status", None) or getattr(mcf, "status", None)).lower(),
            "shipping_cost": None,
            "shipping_currency": None,
            "shipping_cost_confirmed": False,
            "mcf_read_only": True,
            "mcf_order_id": int(mcf.id),
        }
        # Source MCF orders can already be present in the base FBM HTML after
        # their tracking was enriched and the source row became shipped. Keep
        # that existing row, but always override its browser queue to MCF. Only
        # inject a dedicated read-only row when the source row is not already
        # rendered. This prevents duplicate rows while preserving all MCF orders.
        if f'data-order-id="{row_id}"' in html:
            continue
        fragments.append(_row_html(mcf, source))

    if fragments:
        html = html[:tbody_end] + "".join(fragments) + html[tbody_end:]
    return html, payload, len(payload)


def _install() -> None:
    if getattr(dispatch_queue, "_bt38_mcf_visibility_patched", False):
        return

    # FBA classification must never absorb a row that carries positive MCF
    # identity, including historical S02 ORDER_CHANGE rows whose fulfilment type
    # was incorrectly persisted as FBA before MCF identity was attached.
    original_fba_queue_for = fba_visibility._queue_for

    def mcf_safe_fba_queue_for(row):
        if _is_mcf_marketplace_row(row):
            return None
        return original_fba_queue_for(row)

    fba_visibility._queue_for = mcf_safe_fba_queue_for

    original_inject = dispatch_queue._inject

    def aligned_inject(html, payload, counts, fba_count, truncated):
        try:
            html, mcf_payload, mcf_count = _insert_mcf_rows(html, _canonical_mcf_pairs())
        except Exception:
            mcf_payload = {}
            mcf_count = 0

        next_payload = dict(payload or {})
        next_payload.update(mcf_payload)
        next_counts = dict(counts or {})
        next_counts["mcf"] = mcf_count

        rendered = original_inject(html, next_payload, next_counts, fba_count, truncated)
        rendered = rendered.replace(
            "var labels={ready_dispatch:'Ready to dispatch',pending:'Pending',dispatched:'Dispatched',cancelled:'Cancelled',fba:'FBA',replacements:'Replacement',refunds:'Refunds'};",
            "var labels={ready_dispatch:'Ready to dispatch',pending:'Pending',dispatched:'Dispatched',cancelled:'Cancelled',fba:'FBA',mcf:'MCF',replacements:'Replacement',refunds:'Refunds'};",
            1,
        )
        rendered = rendered.replace(
            "addWorkflowButton(tabBar,'fba','FBA');",
            "addWorkflowButton(tabBar,'fba','FBA');\n  addWorkflowButton(tabBar,'mcf','MCF');",
            1,
        )
        return rendered

    dispatch_queue._inject = aligned_inject
    dispatch_queue._bt38_mcf_visibility_patched = True


_install()
