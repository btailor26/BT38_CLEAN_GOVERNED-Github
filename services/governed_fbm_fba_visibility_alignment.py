"""Read-only FBA lifecycle visibility inside the existing FBM workspace.

FBA/AFN rows are presentation-only and share the existing FBM table/controller.
They are loaded with the page working set, then History/lifecycle/search/page-size
operate locally in the browser. No filter action queries the DB, reads a
marketplace/provider, polls, writes inventory, or changes Warehouse.
"""
from __future__ import annotations

from html import escape

from sqlalchemy.orm import joinedload

from extensions import db
from models import MarketplaceOrder
from services import governed_fbm_dispatch_queue_alignment as dispatch_queue

_FBA_TYPES = {"FBA", "AFN"}
_FBA_DISPATCHED = {
    "shipped", "dispatched", "delivered", "fulfilled", "completed",
    "partially_shipped", "partiallyshipped", "picked_up_by_carrier",
    "pickedupbycarrier", "in_transit", "intransit", "out_for_delivery",
    "outfordelivery",
}
_MAX_FBA_ROWS = 300


def _status(row) -> str:
    return str(getattr(row, "status", "") or "").strip().lower()


def _fulfillment(row) -> str:
    return str(getattr(row, "fulfillment_type", "") or "").strip().upper()


def _queue_for(row) -> str | None:
    if _fulfillment(row) not in _FBA_TYPES:
        return None
    status = _status(row)
    if status == "pending":
        return "pending"
    if status in _FBA_DISPATCHED:
        return "fba"
    return None


def _canonical_fba_rows() -> list[MarketplaceOrder]:
    candidates = (
        db.session.query(MarketplaceOrder)
        .filter(
            db.func.upper(db.func.coalesce(MarketplaceOrder.fulfillment_type, "")).in_(tuple(_FBA_TYPES)),
            ~db.func.lower(db.func.coalesce(MarketplaceOrder.status, "")).like("mcf_%"),
            MarketplaceOrder.store_id.isnot(None),
            MarketplaceOrder.marketplace_order_id.isnot(None),
        )
        .options(joinedload(MarketplaceOrder.store), joinedload(MarketplaceOrder.warehouse_stock))
        .order_by(MarketplaceOrder.id.desc())
        .limit(_MAX_FBA_ROWS * 4)
        .all()
    )
    selected = {}
    for row in candidates:
        queue = _queue_for(row)
        if queue is None:
            continue
        key = (int(row.store_id), str(row.marketplace_order_id))
        current = selected.get(key)
        if current is None:
            selected[key] = row
            continue
        current_rank = (1 if _queue_for(current) == "fba" else 0, int(current.id or 0))
        incoming_rank = (1 if queue == "fba" else 0, int(row.id or 0))
        if incoming_rank > current_rank:
            selected[key] = row
    return sorted(selected.values(), key=lambda row: int(row.id or 0), reverse=True)[:_MAX_FBA_ROWS]


def _date_value(row):
    return getattr(row, "marketplace_created_at", None) or getattr(row, "created_at", None) or getattr(row, "processed_at", None)


def _row_html(row: MarketplaceOrder, queue: str) -> str:
    warehouse = getattr(row, "warehouse_stock", None)
    store = getattr(row, "store", None)
    product = str(getattr(warehouse, "product_name", None) or getattr(row, "sku", None) or "—")
    sku = str(getattr(row, "sku", None) or "—")
    store_name = str(getattr(store, "name", None) or "Amazon")
    order_id = str(getattr(row, "marketplace_order_id", None) or "—")
    status = _status(row)
    date = _date_value(row)
    date_text = date.strftime("%d/%m/%Y %H:%M") if date else "—"
    try:
        quantity = int(getattr(row, "quantity", 0) or 0)
    except (TypeError, ValueError):
        quantity = 0
    lifecycle = "FBA Pending" if queue == "pending" else status.replace("_", " ").title()
    shipment = "Amazon fulfilment pending" if queue == "pending" else f"Amazon · {lifecycle}"
    return (
        f'<tr class="fbm-order-row" data-order-id="{int(row.id)}" data-fbm-fba-readonly="1" '
        f'data-lifecycle-status="{escape(status, quote=True)}">'
        '<td class="text-center" data-no-row-click="1"><span class="text-muted">—</span></td>'
        '<td class="fbm-marketplace-cell"><img class="fbm-marketplace-logo" src="/static/img/marketplaces/amazon.png" alt="Amazon" title="Amazon">'
        f'<div class="small text-muted mt-1">{escape(store_name)}</div><span class="badge bg-light text-dark border mt-1">FBA</span></td>'
        f'<td><span class="fw-semibold">{escape(order_id)}</span><div class="small text-muted">{escape(date_text)}</div></td>'
        f'<td class="fbm-product-cell"><strong>{escape(product)}</strong><div class="small text-muted"><code>{escape(sku)}</code></div></td>'
        f'<td>{quantity}</td><td class="fbm-route-cell"><strong>Fulfilment by Amazon</strong><div class="small text-muted mt-1">Read only</div></td>'
        '<td class="fbm-promise-cell"><div class="small text-muted">Amazon managed</div></td>'
        f'<td><strong>{escape(shipment)}</strong></td><td><span class="badge bg-light text-dark border">{escape(lifecycle)}</span></td>'
        '<td class="fbm-action-cell" data-no-row-click="1"><span class="badge bg-light text-dark border">Read only</span></td></tr>'
    )


def _insert_rows(html: str, rows: list[MarketplaceOrder]):
    table_index = html.find('class="table table-hover align-middle mb-0 fbm-orders-table"')
    if table_index < 0:
        return html, {}, 0
    tbody_start = html.find("<tbody>", table_index)
    tbody_end = html.find("</tbody>", tbody_start)
    if tbody_start < 0 or tbody_end < 0:
        return html, {}, 0
    payload = {}
    fragments = []
    fba_count = 0
    for row in rows:
        row_id = str(int(row.id))
        queue = _queue_for(row)
        if queue is None:
            continue
        if queue == "fba":
            fba_count += 1
        if f'data-order-id="{row_id}"' in html:
            continue
        created = _date_value(row)
        payload[row_id] = {
            "queue": queue,
            "status": _status(row),
            "created_at": created.isoformat() if created else None,
            "shipping_cost": None,
            "shipping_currency": None,
            "shipping_cost_confirmed": False,
            "fba_read_only": True,
        }
        fragments.append(_row_html(row, queue))
    if fragments:
        html = html[:tbody_end] + "".join(fragments) + html[tbody_end:]
    return html, payload, fba_count


def _install() -> None:
    if getattr(dispatch_queue, "_bt38_fba_visibility_patched", False):
        return
    original_inject = dispatch_queue._inject

    def aligned_inject(html, payload, _fba_count):
        try:
            html, fba_payload, local_fba_count = _insert_rows(html, _canonical_fba_rows())
        except Exception:
            fba_payload, local_fba_count = {}, 0
        next_payload = dict(payload or {})
        next_payload.update(fba_payload)
        rendered = original_inject(html, next_payload, local_fba_count)
        rendered = rendered.replace(
            "var labels={ready_dispatch:'Ready to dispatch',pending:'Pending',dispatched:'Dispatched',cancelled:'Cancelled',replacements:'Replacement',refunds:'Refunds'};",
            "var labels={ready_dispatch:'Ready to dispatch',pending:'Pending',dispatched:'Dispatched',cancelled:'Cancelled',fba:'FBA',replacements:'Replacement',refunds:'Refunds'};",
            1,
        )
        rendered = rendered.replace(
            f"addTruthLink(tabBar,'FBA','/governed/amazon-fba-stock',{int(local_fba_count)});",
            "addWorkflowButton(tabBar,'fba','FBA');",
            1,
        )
        return rendered

    dispatch_queue._inject = aligned_inject
    dispatch_queue._bt38_fba_visibility_patched = True


_install()
