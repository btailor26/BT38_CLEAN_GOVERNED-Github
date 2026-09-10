"""Present one current FBM commercial-order state on the existing bell.

The bell is a presentation of the already-persisted FBM/order projection. It is
not a webhook feed and it does not own fulfilment state. Marketplace retries,
label assignment, dispatch confirmation, carrier acceptance and in-transit
updates remain audit/FBM-page evidence and must not create fresh bell items.

For a normal FBM sale the bell presents one stable "Get ready to dispatch"
item until existing persisted delivery truth reaches Delivered. Genuine issue
states (return/refund/cancellation/case/dispute/chargeback/replacement) remain
visible because they require seller attention.

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

_FINAL_BELL_STATUSES = {
    "delivered",
    "return_requested",
    "returned",
    "refund_requested",
    "refunded",
    "replacement_requested",
    "replacement",
    "case_open",
    "dispute",
    "chargeback",
    "cancel_requested",
    "cancelled",
}


def _platform_label(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "ebay":
        return "eBay"
    if normalized == "amazon":
        return "Amazon"
    return str(value or "Marketplace").strip() or "Marketplace"


def _sale_product_title(record: dict) -> str:
    current = str(record.get("title") or record.get("message") or "").strip()
    for prefix in ("Get ready to dispatch · ", "Sale · "):
        if current.startswith(prefix):
            current = current[len(prefix):].strip()
            break

    platform_label = _platform_label(record.get("platform"))
    platform_prefix = f"{platform_label} · "
    if current.startswith(platform_prefix):
        current = current[len(platform_prefix):].strip()

    return current or str(
        record.get("product_title")
        or record.get("sku")
        or record.get("order_id")
        or "Order"
    ).strip()


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
    """Prefer the stronger routine sale state, then the earliest stable sale time.

    Retry/recovery writes can advance MarketplaceOrder.updated_at or create a
    stronger sibling later. They must not make the same commercial sale look
    new again on the bell.
    """
    current_status = str(current.get("lifecycle_status") or "").strip().lower()
    incoming_status = str(incoming.get("lifecycle_status") or "").strip().lower()
    current_rank = _ROUTINE_SALE_RANK.get(current_status, -1)
    incoming_rank = _ROUTINE_SALE_RANK.get(incoming_status, -1)
    if incoming_rank != current_rank:
        return incoming if incoming_rank > current_rank else current
    return (
        incoming
        if str(incoming.get("created_at") or "") < str(current.get("created_at") or "")
        else current
    )


def _is_final_bell_record(record: dict) -> bool:
    status = str(record.get("lifecycle_status") or "").strip().lower()
    log_type = str(record.get("log_type") or "").strip().lower()
    return status in _FINAL_BELL_STATUSES or log_type == "fbm_delivered"


def _align_ready_sale(record: dict) -> dict:
    aligned = dict(record)
    platform = str(aligned.get("platform") or "Marketplace").strip()
    platform_label = _platform_label(platform)
    product_title = _sale_product_title(aligned)
    order_id = str(aligned.get("order_id") or "").strip()

    aligned["status_label"] = "Get ready to dispatch"
    aligned["title"] = f"Get ready to dispatch · {platform_label} · {product_title}"
    aligned["message"] = aligned["title"]
    aligned["event_key"] = f"fbm-ready:{platform.lower()}:{order_id}"
    aligned["presentation_source"] = "existing_fbm_order_state"
    return aligned


def _collapse_logical_bell_records(records: list[dict], limit: int) -> list[dict]:
    """Keep one Ready item per order until a final persisted state exists."""
    final_orders: set[tuple[str, str]] = set()
    final_records: list[dict] = []

    for record in records:
        if not _is_final_bell_record(record):
            continue
        order_id = str(record.get("order_id") or "").strip()
        if not order_id:
            continue
        platform = str(record.get("platform") or "").strip().lower()
        final_orders.add((platform, order_id))
        final_records.append(record)

    logical_sales: dict[tuple[str, str, str, str], dict] = {}
    for record in records:
        log_type = str(record.get("log_type") or "").strip().lower()
        if log_type != "marketplace_sale":
            continue

        identity = _sale_identity(record)
        if identity is None:
            continue
        if (identity[0], identity[1]) in final_orders:
            continue

        aligned = _align_ready_sale(record)
        existing = logical_sales.get(identity)
        logical_sales[identity] = (
            aligned if existing is None else _prefer_sale(existing, aligned)
        )

    collapsed = final_records + list(logical_sales.values())

    # Final records are already persisted lifecycle truth. Ready records keep
    # the original sale time, so webhook retries cannot move them to the top.
    collapsed.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)

    seen: set[str] = set()
    unique: list[dict] = []
    for record in collapsed:
        platform = str(record.get("platform") or "").strip().lower()
        order_id = str(record.get("order_id") or "").strip()
        status = str(record.get("lifecycle_status") or "").strip().lower()
        log_type = str(record.get("log_type") or "").strip().lower()

        if log_type == "marketplace_sale":
            key = f"ready:{platform}:{order_id}"
        elif order_id and status:
            key = f"final:{platform}:{order_id}:{status}"
        else:
            key = str(record.get("event_key") or "").strip()

        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(record)
        if len(unique) >= limit:
            break

    return unique


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
            payload["presentation_source"] = "existing_fbm_order_state"
            payload["polling"] = False
            return jsonify(payload)

        logical_order_bell._bt38_logical_order_bell = True
        app.view_functions[endpoint] = logical_order_bell

    aligned_install._bt38_logical_bell_aligned = True
    small_alignment._install_final_bell_alignment = aligned_install


install_governed_fbm_logical_bell_alignment()
