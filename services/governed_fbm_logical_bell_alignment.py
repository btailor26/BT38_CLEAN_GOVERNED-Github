"""Collapse the existing FBM bell to one logical commercial order event.

Historical eBay importer rows can preserve more than one provider line identity
for the same commercial order/SKU. The bell must not turn those audit rows into
multiple user actions merely because one persisted sale event says ``pending``
and another says ``unshipped``. It must also stop presenting the original sale
once the existing bell projection contains a later shipment lifecycle event for
that same order.

This alignment wraps only the already-installed bell endpoint. It performs no
DB query, marketplace/provider read, polling, scheduling, order mutation or
shipment creation.
"""
from __future__ import annotations

from flask import jsonify, request
from flask_login import login_required

from services import governed_fbm_small_alignment as small_alignment


_ROUTINE_SALE_RANK = {
    "": -1,
    "pending": 0,
    "order": 1,
    "confirmed": 1,
    "unshipped": 1,
}


def _sale_identity(record: dict) -> tuple[str, str, str, str] | None:
    order_id = str(record.get("order_id") or "").strip()
    if not order_id:
        return None
    return (
        str(record.get("platform") or "").strip().lower(),
        order_id,
        str(record.get("sku") or "").strip(),
        str(record.get("quantity") or "").strip(),
    )


def _prefer_sale(current: dict, incoming: dict) -> dict:
    """Prefer the stronger routine sale state, then the newest persisted event."""
    current_status = str(current.get("lifecycle_status") or "").strip().lower()
    incoming_status = str(incoming.get("lifecycle_status") or "").strip().lower()
    current_rank = _ROUTINE_SALE_RANK.get(current_status, -1)
    incoming_rank = _ROUTINE_SALE_RANK.get(incoming_status, -1)
    if incoming_rank != current_rank:
        return incoming if incoming_rank > current_rank else current
    return (
        incoming
        if str(incoming.get("created_at") or "") > str(current.get("created_at") or "")
        else current
    )


def _collapse_logical_bell_records(records: list[dict], limit: int) -> list[dict]:
    progressed_orders: set[tuple[str, str]] = set()
    for record in records:
        log_type = str(record.get("log_type") or "").strip().lower()
        if log_type not in small_alignment._BELL_SHIPMENT_LOG_TYPES:
            continue
        order_id = str(record.get("order_id") or "").strip()
        if not order_id:
            continue
        progressed_orders.add((
            str(record.get("platform") or "").strip().lower(),
            order_id,
        ))

    logical_sales: dict[tuple[str, str, str, str], dict] = {}
    other_records: list[dict] = []
    for record in records:
        log_type = str(record.get("log_type") or "").strip().lower()
        if log_type != "marketplace_sale":
            other_records.append(record)
            continue

        identity = _sale_identity(record)
        if identity is None:
            other_records.append(record)
            continue
        if (identity[0], identity[1]) in progressed_orders:
            continue

        existing = logical_sales.get(identity)
        logical_sales[identity] = (
            record if existing is None else _prefer_sale(existing, record)
        )

    collapsed = other_records + list(logical_sales.values())
    collapsed.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return collapsed[:limit]


def install_governed_fbm_logical_bell_alignment() -> None:
    """Patch the existing small-alignment installer before Flask installs it."""
    original_install = small_alignment._install_final_bell_alignment
    if getattr(original_install, "_bt38_logical_bell_aligned", False):
        return

    def aligned_install(app) -> None:
        original_install(app)
        endpoint = "governed.governed_ui_notifications"
        current = app.view_functions.get(endpoint)
        if current is None or getattr(current, "_bt38_logical_order_bell", False):
            return

        @login_required
        def logical_order_bell():
            response = current()
            if isinstance(response, tuple):
                return response
            payload = response.get_json(silent=True) if hasattr(response, "get_json") else None
            if not isinstance(payload, dict) or payload.get("success") is not True:
                return response

            try:
                limit = int(request.args.get("limit") or 20)
            except Exception:
                limit = 20
            limit = max(1, min(limit, 50))

            records = _collapse_logical_bell_records(
                list(payload.get("records") or []),
                limit,
            )
            payload["records"] = records
            payload["latest_event_at"] = records[0].get("created_at") if records else None
            return jsonify(payload)

        logical_order_bell._bt38_logical_order_bell = True
        app.view_functions[endpoint] = logical_order_bell

    aligned_install._bt38_logical_bell_aligned = True
    small_alignment._install_final_bell_alignment = aligned_install


install_governed_fbm_logical_bell_alignment()
