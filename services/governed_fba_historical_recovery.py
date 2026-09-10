"""Finite exact-order recovery for historical Amazon FBA/AFN order truth.

This is an operator/recovery helper, not a runtime poller. It reuses the existing
Amazon store connection and MarketplaceOrder rows, reads one exact Amazon order
and its exact order items, and fills Amazon-owned lifecycle/order/promise facts.

Safety boundaries:
- FBA/AFN only; MCF and FBM are excluded.
- No Warehouse quantity mutation.
- No Product Linking/group propagation.
- No marketplace write, shipment confirmation, label purchase, worker or poller.
- Quantity/SKU/title are only filled from exact Amazon order-item truth.
- Shipping cost is never invented; Orders API recovery leaves it unavailable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

from extensions import db
from models import MarketplaceOrder, Store
from services.governed_marketplace_order_import import _amazon_credentials, _store_credentials


_FBA_TYPES = {"FBA", "AFN"}
_STATUS_MAP = {
    "PENDING": "pending",
    "UNSHIPPED": "pending",
    "PARTIALLYSHIPPED": "partially_shipped",
    "SHIPPED": "shipped",
    "FULFILLED": "shipped",
    "DISPATCHED": "shipped",
    "DELIVERED": "delivered",
    "CANCELED": "cancelled",
    "CANCELLED": "cancelled",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_amazon_dt(value: Any) -> datetime | None:
    raw = _clean(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _current_status(order_payload: dict[str, Any]) -> str | None:
    raw = _clean(order_payload.get("OrderStatus") or order_payload.get("orderStatus")).upper()
    return _STATUS_MAP.get(raw)


def _persist_operational_truth(*, store_id: int, order_id: str, order_payload: dict[str, Any]) -> dict[str, Any]:
    shipping_service = _clean(
        order_payload.get("ShipServiceLevel")
        or order_payload.get("ShipmentServiceLevelCategory")
        or order_payload.get("ShippingServiceLevel")
    ) or None
    ship_by = _parse_amazon_dt(order_payload.get("LatestShipDate") or order_payload.get("EarliestShipDate"))
    earliest_delivery = _parse_amazon_dt(order_payload.get("EarliestDeliveryDate"))
    latest_delivery = _parse_amazon_dt(order_payload.get("LatestDeliveryDate"))
    now = datetime.utcnow()

    db.session.execute(
        text(
            """
            INSERT INTO fbm_order_operational_state
              (store_id, marketplace_order_id, platform, parcel, shipping_service,
               ship_by_at, earliest_delivery_at, latest_delivery_at,
               marketplace_checked_at, created_at, updated_at)
            VALUES
              (:store_id,:order_id,'amazon','{}'::json,:shipping_service,
               :ship_by,:earliest_delivery,:latest_delivery,:now,:now,:now)
            ON CONFLICT (store_id, marketplace_order_id) DO UPDATE SET
              platform='amazon',
              shipping_service=COALESCE(EXCLUDED.shipping_service, fbm_order_operational_state.shipping_service),
              ship_by_at=COALESCE(EXCLUDED.ship_by_at, fbm_order_operational_state.ship_by_at),
              earliest_delivery_at=COALESCE(EXCLUDED.earliest_delivery_at, fbm_order_operational_state.earliest_delivery_at),
              latest_delivery_at=COALESCE(EXCLUDED.latest_delivery_at, fbm_order_operational_state.latest_delivery_at),
              marketplace_checked_at=EXCLUDED.marketplace_checked_at,
              updated_at=EXCLUDED.updated_at
            """
        ),
        {
            "store_id": int(store_id),
            "order_id": order_id,
            "shipping_service": shipping_service,
            "ship_by": ship_by,
            "earliest_delivery": earliest_delivery,
            "latest_delivery": latest_delivery,
            "now": now,
        },
    )
    return {
        "shipping_service": shipping_service,
        "ship_by_at": ship_by.isoformat() if ship_by else None,
        "earliest_delivery_at": earliest_delivery.isoformat() if earliest_delivery else None,
        "latest_delivery_at": latest_delivery.isoformat() if latest_delivery else None,
    }


def recover_exact_fba_order(*, store: Store, marketplace_order_id: str) -> dict[str, Any]:
    """Recover one existing FBA/AFN order from exact Amazon Orders API truth."""
    from sp_api.api import Orders
    from sp_api.base import Marketplaces

    order_id = _clean(marketplace_order_id)
    rows = (
        MarketplaceOrder.query
        .filter(
            MarketplaceOrder.store_id == int(store.id),
            MarketplaceOrder.marketplace_order_id == order_id,
        )
        .order_by(MarketplaceOrder.id.asc())
        .all()
    )
    fba_rows = [row for row in rows if _clean(getattr(row, "fulfillment_type", None)).upper() in _FBA_TYPES]
    if not fba_rows:
        return {
            "success": True,
            "skipped": True,
            "reason": "existing_fba_order_missing",
            "order_id": order_id,
            "stock_mutation_started": False,
            "marketplace_write_started": False,
        }

    creds = _store_credentials(store)
    marketplace_id = _clean(creds.get("marketplace_id")) or "A1F83G8C2ARO7P"
    client = Orders(marketplace=Marketplaces.UK, credentials=_amazon_credentials(store))

    order_response = client.get_order(order_id)
    order_payload = order_response.payload or {}
    if _clean(order_payload.get("AmazonOrderId")) not in {"", order_id}:
        raise RuntimeError("amazon_exact_fba_order_identity_mismatch")

    fulfillment_channel = _clean(order_payload.get("FulfillmentChannel")).upper()
    if fulfillment_channel and fulfillment_channel != "AFN":
        return {
            "success": False,
            "skipped": True,
            "reason": "amazon_exact_order_not_afn",
            "order_id": order_id,
            "fulfillment_channel": fulfillment_channel,
            "stock_mutation_started": False,
            "marketplace_write_started": False,
        }

    item_response = client.get_order_items(order_id)
    item_payload = item_response.payload or {}
    items = [item for item in (item_payload.get("OrderItems") or []) if isinstance(item, dict)]
    items_by_id = {_clean(item.get("OrderItemId")): item for item in items if _clean(item.get("OrderItemId"))}
    items_by_sku = {_clean(item.get("SellerSKU")): item for item in items if _clean(item.get("SellerSKU"))}

    lifecycle = _current_status(order_payload)
    lifecycle_updates = 0
    detail_updates = 0
    for row in fba_rows:
        item = items_by_id.get(_clean(getattr(row, "marketplace_order_item_id", None)))
        if item is None:
            item = items_by_sku.get(_clean(getattr(row, "sku", None)))

        changed = False
        if item is not None:
            seller_sku = _clean(item.get("SellerSKU"))
            quantity = _safe_int(item.get("QuantityOrdered"))
            title = _clean(item.get("Title"))
            if seller_sku and not _clean(getattr(row, "sku", None)):
                row.sku = seller_sku
                changed = True
            if quantity is not None and int(getattr(row, "quantity", 0) or 0) <= 0:
                row.quantity = quantity
                changed = True
            if title and hasattr(row, "product_name") and not _clean(getattr(row, "product_name", None)):
                row.product_name = title
                changed = True

        if lifecycle and _clean(getattr(row, "status", None)).lower() != lifecycle:
            row.status = lifecycle
            lifecycle_updates += 1
            changed = True

        if changed:
            row.updated_at = datetime.utcnow()
            detail_updates += 1

    operational = _persist_operational_truth(
        store_id=int(store.id),
        order_id=order_id,
        order_payload=order_payload,
    )
    db.session.commit()

    return {
        "success": True,
        "skipped": False,
        "order_id": order_id,
        "marketplace_id": marketplace_id,
        "amazon_order_status": _clean(order_payload.get("OrderStatus")) or None,
        "persisted_lifecycle": lifecycle,
        "rows_considered": len(fba_rows),
        "items_returned": len(items),
        "rows_updated": detail_updates,
        "lifecycle_updates": lifecycle_updates,
        "operational_truth": operational,
        "shipping_cost": None,
        "shipping_cost_reason": "not_available_from_orders_api",
        "stock_mutation_started": False,
        "warehouse_mutation_started": False,
        "group_propagation_started": False,
        "marketplace_write_started": False,
        "polling_started": False,
        "worker_started": False,
    }


def recover_historical_pending_fba(*, store_id: int | None = None, limit: int = 500) -> dict[str, Any]:
    """Finite DB-selected recovery for persisted FBA/AFN rows still marked Pending."""
    query = (
        db.session.query(MarketplaceOrder.store_id, MarketplaceOrder.marketplace_order_id)
        .filter(
            db.func.upper(db.func.coalesce(MarketplaceOrder.fulfillment_type, "")).in_(tuple(_FBA_TYPES)),
            db.func.lower(db.func.coalesce(MarketplaceOrder.status, "")) == "pending",
            MarketplaceOrder.store_id.isnot(None),
            MarketplaceOrder.marketplace_order_id.isnot(None),
        )
        .distinct()
        .order_by(MarketplaceOrder.marketplace_order_id.asc())
        .limit(max(1, min(int(limit or 500), 2000)))
    )
    if store_id is not None:
        query = query.filter(MarketplaceOrder.store_id == int(store_id))

    selected = [(int(sid), _clean(oid)) for sid, oid in query.all() if sid and _clean(oid)]
    results = []
    recovered = failed = 0
    for sid, order_id in selected:
        store = db.session.get(Store, sid)
        if store is None or not bool(getattr(store, "is_active", False)) or "amazon" not in _clean(getattr(store, "platform", None)).lower():
            continue
        try:
            result = recover_exact_fba_order(store=store, marketplace_order_id=order_id)
            recovered += 1 if result.get("success") else 0
        except Exception as exc:
            db.session.rollback()
            failed += 1
            result = {
                "success": False,
                "order_id": order_id,
                "store_id": sid,
                "error": str(exc)[:1000],
                "stock_mutation_started": False,
                "marketplace_write_started": False,
            }
        results.append(result)

    return {
        "success": failed == 0,
        "operator_action": True,
        "selected": len(selected),
        "recovered": recovered,
        "failed": failed,
        "results": results,
        "stock_mutation_started": False,
        "warehouse_mutation_started": False,
        "group_propagation_started": False,
        "marketplace_write_started": False,
        "polling_started": False,
        "worker_started": False,
    }
