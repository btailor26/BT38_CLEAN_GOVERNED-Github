"""BT38 governed webhook execution bridge.

One clear path:
notification -> grouped check -> warehouse truth -> governed_push_execution

Rules:
- grouped SKU/listing = group-level notification
- ungrouped SKU/listing = warehouse SKU-level notification
- notification never calls marketplace adapters directly
- marketplace propagation stays behind governed_push_execution/governed_execution
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def process_marketplace_notification(*, marketplace: str, payload: dict, actor: str = "marketplace_webhook") -> Dict[str, Any]:
    from extensions import db
    from models import MarketplaceListing, SystemLog, WarehouseStock
    from services.governed_push_execution import push_group_listings, push_marketplace_listing

    payload = dict(payload or {})
    marketplace = str(marketplace or payload.get("marketplace") or "").strip().lower()
    event_type = _event_type(payload)

    listing = _find_listing(MarketplaceListing, marketplace, payload)
    if not listing:
        return _log_result(
            status="unresolved",
            marketplace=marketplace,
            event_type=event_type,
            reason="Notification received but no marketplace listing could be matched.",
            payload=payload,
        )

    stock = listing.warehouse_stock
    if not stock:
        return _log_result(
            status="unlinked",
            marketplace=marketplace,
            event_type=event_type,
            reason="Notification matched listing but listing is not linked to warehouse stock.",
            payload=payload,
            listing_id=listing.id,
        )

    quantity = _extract_quantity(payload)
    is_stock_event = _is_stock_decrement_event(event_type, payload)

    if not is_stock_event or quantity <= 0:
        return _log_result(
            status="stored_no_stock_change",
            marketplace=marketplace,
            event_type=event_type,
            reason="Notification stored but did not contain a confirmed stock-decrement event.",
            payload=payload,
            listing_id=listing.id,
            warehouse_stock_id=stock.id,
        )

    group_context = _resolve_group_context(listing=listing, stock=stock)
    grouped = bool(group_context.get("grouped"))
    group_id = group_context.get("group_id")

    before_qty = int(getattr(stock, "available_quantity", 0) or 0)

    if grouped:
        if not group_id:
            return _log_result(
                status="group_unresolved",
                marketplace=marketplace,
                event_type=event_type,
                reason="DB says listing/stock is grouped but no group_id could be resolved.",
                payload=payload,
                listing_id=listing.id,
                warehouse_stock_id=stock.id,
                group_context=group_context,
            )

        _apply_group_stock_change(stock.id, -quantity)
        db.session.commit()

        push_result = push_group_listings(
            group_id=int(group_id),
            actor=actor,
            source=f"webhook_{marketplace}_group_notification",
            actor_user=None,
        )

        return _log_result(
            status="group_processed",
            marketplace=marketplace,
            event_type=event_type,
            reason="Grouped notification resolved from DB, processed through group authority, then warehouse truth.",
            payload=payload,
            listing_id=listing.id,
            warehouse_stock_id=stock.id,
            group_id=int(group_id),
            group_context=group_context,
            before_qty=before_qty,
            after_qty=int(getattr(stock, "available_quantity", 0) or 0),
            push_result=push_result,
        )

    stock.available_quantity = max(0, before_qty - quantity)
    db.session.commit()

    push_result = push_marketplace_listing(
        listing_id=listing.id,
        actor=actor,
        source=f"webhook_{marketplace}_warehouse_notification",
        actor_user=None,
    )

    return _log_result(
        status="warehouse_processed",
        marketplace=marketplace,
        event_type=event_type,
        reason="Ungrouped notification processed through warehouse authority.",
        payload=payload,
        listing_id=listing.id,
        warehouse_stock_id=stock.id,
        before_qty=before_qty,
        after_qty=int(getattr(stock, "available_quantity", 0) or 0),
        push_result=push_result,
    )


def _resolve_group_context(*, listing, stock) -> Dict[str, Any]:
    """Resolve grouped/not-grouped from DB authority only.

    Payload identifies the event.
    DB relationship fields decide whether the event is grouped.
    """
    from extensions import db
    from models import MarketplaceListing

    listing_group_id = getattr(listing, "master_product_group_id", None)
    stock_group_id = getattr(stock, "master_product_group_id", None)
    stock_group_controlled = bool(getattr(stock, "is_group_controlled", False))

    group_id = stock_group_id or listing_group_id

    linked_group_members = []
    linked_stock_members = []

    if group_id:
        linked_group_members = (
            db.session.query(MarketplaceListing.id)
            .filter(MarketplaceListing.master_product_group_id == int(group_id))
            .filter(MarketplaceListing.is_active == True)  # noqa: E712
            .all()
        )

    if getattr(stock, "id", None):
        linked_stock_members = (
            db.session.query(MarketplaceListing.id)
            .filter(MarketplaceListing.warehouse_stock_id == int(stock.id))
            .filter(MarketplaceListing.is_active == True)  # noqa: E712
            .all()
        )

    grouped = bool(
        group_id
        or stock_group_controlled
        or len(linked_group_members) > 1
        or len(linked_stock_members) > 1
    )

    return {
        "grouped": grouped,
        "group_id": int(group_id) if group_id else None,
        "listing_id": getattr(listing, "id", None),
        "listing_group_id": int(listing_group_id) if listing_group_id else None,
        "warehouse_stock_id": getattr(stock, "id", None),
        "stock_group_id": int(stock_group_id) if stock_group_id else None,
        "stock_is_group_controlled": stock_group_controlled,
        "linked_group_member_count": len(linked_group_members),
        "linked_stock_member_count": len(linked_stock_members),
        "authority": "database_relationship_state",
    }


def _apply_group_stock_change(warehouse_stock_id: int, quantity_delta: int) -> None:
    try:
        from group_resolution import apply_group_quantity_change
        apply_group_quantity_change(
            warehouse_stock_id=int(warehouse_stock_id),
            quantity_delta=int(quantity_delta),
            reason="marketplace_webhook_notification",
        )
        return
    except Exception:
        pass

    from extensions import db
    from models import WarehouseStock

    stock = db.session.get(WarehouseStock, int(warehouse_stock_id))
    if stock:
        before = int(getattr(stock, "available_quantity", 0) or 0)
        stock.available_quantity = max(0, before + int(quantity_delta))


def _find_listing(MarketplaceListing, marketplace: str, payload: dict):
    identifiers = _flatten_values(payload)

    listing_id_keys = {"listing_id", "marketplace_listing_id"}
    external_keys = {"external_listing_id", "item_id", "itemid", "listingid", "orderlineitemid"}
    sku_keys = {"sku", "seller_sku", "sellersku", "external_sku"}

    for key in listing_id_keys:
        value = _deep_get(payload, key)
        if value:
            try:
                listing = MarketplaceListing.query.get(int(value))
                if listing:
                    return listing
            except Exception:
                pass

    for key in external_keys:
        value = _deep_get(payload, key)
        if value:
            listing = (
                MarketplaceListing.query
                .filter(MarketplaceListing.external_listing_id == str(value))
                .first()
            )
            if listing:
                return listing

    for key in sku_keys:
        value = _deep_get(payload, key)
        if value:
            query = MarketplaceListing.query.filter(MarketplaceListing.external_sku == str(value))
            if marketplace:
                query = query.join(MarketplaceListing.store).filter_by(platform=marketplace)
            listing = query.first()
            if listing:
                return listing

    for value in identifiers:
        text = str(value).strip()
        if not text:
            continue
        listing = (
            MarketplaceListing.query
            .filter(
                (MarketplaceListing.external_listing_id == text)
                | (MarketplaceListing.external_sku == text)
            )
            .first()
        )
        if listing:
            return listing

    return None


def _event_type(payload: dict) -> str:
    return str(
        payload.get("event_type")
        or payload.get("eventType")
        or payload.get("notificationType")
        or payload.get("type")
        or payload.get("topic")
        or "marketplace_notification"
    ).strip().lower()


def _is_stock_decrement_event(event_type: str, payload: dict) -> bool:
    text = " ".join(str(v).lower() for v in _flatten_values(payload))
    combined = f"{event_type} {text}"
    return any(word in combined for word in ["order", "sale", "sold", "transaction", "paid", "purchase"])


def _extract_quantity(payload: dict) -> int:
    for key in ["quantity", "qty", "quantity_sold", "quantitySold", "orderQuantity", "amount"]:
        value = _deep_get(payload, key)
        if value is not None:
            try:
                qty = int(value)
                if qty > 0:
                    return qty
            except Exception:
                pass
    return 1


def _deep_get(obj: Any, key: str):
    key_lower = str(key).lower()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() == key_lower:
                return v
            found = _deep_get(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _deep_get(item, key)
            if found is not None:
                return found
    return None


def _flatten_values(obj: Any):
    values = []
    if isinstance(obj, dict):
        for v in obj.values():
            values.extend(_flatten_values(v))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_flatten_values(item))
    else:
        values.append(obj)
    return values


def _log_result(**data) -> Dict[str, Any]:
    from extensions import db
    from models import SystemLog

    safe = dict(data)
    payload = safe.pop("payload", {}) or {}

    try:
        db.session.add(SystemLog(
            log_type="governed_webhook_execution",
            message=f"{safe.get('marketplace')} webhook execution {safe.get('status')}: {safe.get('event_type')}",
            details=str({**safe, "payload_keys": list(payload.keys())})[:1000],
            created_at=datetime.utcnow(),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return {
        "ok": safe.get("status") in {"group_processed", "warehouse_processed", "stored_no_stock_change"},
        "success": safe.get("status") in {"group_processed", "warehouse_processed", "stored_no_stock_change"},
        "governed": True,
        **safe,
    }
