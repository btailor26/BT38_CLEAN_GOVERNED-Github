"""
BT38 governed marketplace order import.

One clear path only:
runtime import refresh
-> governed marketplace order import
-> MarketplaceOrder
-> governed order stock mutation bridge

No legacy processor restore.
No unproven marketplace API calls.
No app import side effects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from extensions import db
from models import Store, MarketplaceOrder, MarketplaceListing, SyncLog


def _text(value: Any) -> str:
    return str(value or "").strip()


def _find_listing(store: Store, sku: str):
    if not sku:
        return None
    return (
        MarketplaceListing.query
        .filter(
            MarketplaceListing.store_id == store.id,
            MarketplaceListing.external_sku == sku,
            MarketplaceListing.is_active == True,  # noqa: E712
        )
        .order_by(
            MarketplaceListing.warehouse_stock_id.is_(None),
            MarketplaceListing.updated_at.desc(),
            MarketplaceListing.id.desc(),
        )
        .first()
    )


def upsert_governed_marketplace_order_line(
    *,
    store: Store,
    marketplace_order_id: str,
    marketplace_order_item_id: str,
    sku: str,
    quantity: int,
    unit_price: float = 0.0,
    fulfillment_type: str = "FBM",
) -> dict[str, Any]:
    sku = _text(sku)
    order_id = _text(marketplace_order_id)
    item_id = _text(marketplace_order_item_id) or order_id
    qty = max(1, int(quantity or 1))

    if not order_id or not sku:
        return {
            "success": False,
            "skipped": True,
            "reason": "missing_order_id_or_sku",
            "order_id": order_id,
            "sku": sku,
        }

    listing = _find_listing(store, sku)
    warehouse_stock_id = getattr(listing, "warehouse_stock_id", None) if listing else None
    key = f"{store.id}:{order_id}:{item_id}:{sku}"

    order = MarketplaceOrder.query.filter_by(idempotency_key=key).first()
    created = False

    if not order:
        order = MarketplaceOrder(
            store_id=store.id,
            marketplace_order_id=order_id,
            marketplace_order_item_id=item_id,
            sku=sku,
            quantity=qty,
            warehouse_stock_id=warehouse_stock_id,
            fulfillment_type=fulfillment_type,
            status="pending",
            idempotency_key=key,
        )
        db.session.add(order)
        created = True

    order.store_id = store.id
    order.marketplace_order_id = order_id
    order.marketplace_order_item_id = item_id
    order.sku = sku
    order.quantity = qty
    order.warehouse_stock_id = warehouse_stock_id
    order.fulfillment_type = fulfillment_type
    order.unit_price = float(unit_price or 0.0)
    order.line_total = float(unit_price or 0.0) * qty
    order.updated_at = datetime.utcnow()

    db.session.flush()

    return {
        "success": True,
        "created": created,
        "order_id": order.marketplace_order_id,
        "sku": order.sku,
        "quantity": order.quantity,
        "warehouse_stock_id": order.warehouse_stock_id,
        "idempotency_key": order.idempotency_key,
    }


def _not_wired(store: Store, marketplace: str) -> dict[str, Any]:
    db.session.add(SyncLog(
        store_id=store.id,
        status="success",
        items_synced=0,
        message=f"governed_{marketplace}_order_import skipped: marketplace order reader not yet wired",
        created_at=datetime.utcnow(),
    ))
    db.session.commit()

    return {
        "success": True,
        "governed": True,
        "marketplace": marketplace,
        "imported": 0,
        "created": 0,
        "skipped": True,
        "reason": "marketplace_order_reader_not_yet_wired",
    }


def run_governed_marketplace_order_import(store_id=None, source: str = "governed_marketplace_order_import") -> dict[str, Any]:
    stores = (
        Store.query
        .filter(Store.is_active == True)  # noqa: E712
        .filter(Store.store_mode == "live")
        .order_by(Store.id)
        .all()
    )

    if store_id:
        stores = [s for s in stores if int(s.id) == int(store_id)]

    results = []

    for store in stores:
        platform = str(store.platform or "").strip().lower()

        if "amazon" in platform:
            results.append({
                "store_id": store.id,
                "store": store.name,
                "platform": store.platform,
                "order_import": _not_wired(store, "amazon"),
            })
            continue

        if "ebay" in platform:
            results.append({
                "store_id": store.id,
                "store": store.name,
                "platform": store.platform,
                "order_import": _not_wired(store, "ebay"),
            })
            continue

    return {
        "success": True,
        "governed": True,
        "source": source,
        "results": results,
    }
