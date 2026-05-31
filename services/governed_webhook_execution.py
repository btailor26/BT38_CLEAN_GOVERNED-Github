"""BT38 governed webhook execution bridge.

Step 1 notification wiring only.

Three-step operating model:
1. Notification = immediate awareness and DB/log classification.
2. 15-minute light sync = verification/alignment.
3. 8-hour full sync = reconciliation.

Rules:
- Existing stock-changing notification path is preserved.
- Non-stock business notifications are classified and logged.
- FBA pending is classified and logged, but does not change warehouse stock.
- Notification never calls marketplace adapters directly.
- No dashboard, route, sync, Product Linking, or adapter changes live here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def process_marketplace_notification(*, marketplace: str, payload: dict, actor: str = "marketplace_webhook") -> Dict[str, Any]:
    from extensions import db
    from models import MarketplaceListing
    from services.governed_push_execution import push_group_listings, push_marketplace_listing

    payload = dict(payload or {})
    marketplace = str(marketplace or payload.get("marketplace") or "").strip().lower()
    event_type = _event_type(payload)
    business_event = _classify_business_event(event_type, payload)

    listing = _find_listing(MarketplaceListing, marketplace, payload)
    if not listing:
        return _log_result(
            status="unresolved",
            marketplace=marketplace,
            event_type=event_type,
            business_event=business_event,
            reason="Notification received but no marketplace listing could be matched.",
            payload=payload,
        )

    stock = listing.warehouse_stock
    if not stock:
        return _log_result(
            status="unlinked",
            marketplace=marketplace,
            event_type=event_type,
            business_event=business_event,
            reason="Notification matched listing but listing is not linked to warehouse stock.",
            payload=payload,
            listing_id=listing.id,
        )

    quantity = _extract_quantity(payload)
    is_stock_event = _is_stock_decrement_event(event_type, payload)

    if not is_stock_event or quantity <= 0:
        return _log_result(
            status=f"{business_event}_stored",
            marketplace=marketplace,
            event_type=event_type,
            business_event=business_event,
            reason=_business_reason(business_event),
            payload=payload,
            listing_id=listing.id,
            warehouse_stock_id=stock.id,
            stock_changed=False,
            correction_started=False,
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
                business_event=business_event,
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
            business_event=business_event,
            reason="Grouped stock-changing notification updated warehouse truth and triggered existing correction path.",
            payload=payload,
            listing_id=listing.id,
            warehouse_stock_id=stock.id,
            group_id=int(group_id),
            group_context=group_context,
            before_qty=before_qty,
            after_qty=int(getattr(stock, "available_quantity", 0) or 0),
            stock_changed=True,
            correction_started=True,
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
        business_event=business_event,
        reason="Ungrouped stock-changing notification updated warehouse truth and triggered existing correction path.",
        payload=payload,
        listing_id=listing.id,
        warehouse_stock_id=stock.id,
        before_qty=before_qty,
        after_qty=int(getattr(stock, "available_quantity", 0) or 0),
        stock_changed=True,
        correction_started=True,
        push_result=push_result,
    )


def _resolve_group_context(*, listing, stock) -> Dict[str, Any]:
    """Resolve grouped/not-grouped from DB authority only."""
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


def _classify_business_event(event_type: str, payload: dict) -> str:
    text = " ".join(str(v).lower() for v in _flatten_values(payload))
    combined = f"{event_type} {text}"

    checks = [
        ("fba_pending", ["fba pending", "afn pending", "pending fba", "pending inventory", "inbound pending"]),
        ("fba_received", ["fba received", "afn received", "received by amazon", "inbound received"]),
        ("fba_adjustment", ["fba adjustment", "inventory adjustment", "afn adjustment"]),
        ("fba_lost", ["fba lost", "lost inventory", "inventory lost"]),
        ("fba_damaged", ["fba damaged", "damaged inventory", "warehouse damaged"]),
        ("fba_reimbursement", ["fba reimbursement", "reimbursement", "reimbursed"]),
        ("customer_message", ["message", "buyer message", "customer message", "inbox", "unread"]),
        ("return", ["return", "return request", "refund requested"]),
        ("case", ["case", "dispute", "claim", "a-to-z", "chargeback"]),
        ("listing_created", ["listing created", "item listed", "offer created", "new listing"]),
        ("listing_removed", ["listing removed", "listing ended", "item ended", "offer deleted", "listing blocked", "suppressed"]),
        ("payment_deferred", ["deferred", "reserve", "hold", "held", "pending payout"]),
        ("payout", ["payout", "disbursement", "settlement", "payment released", "paid out"]),
        ("tracking", ["tracking", "tracking uploaded", "shipment confirmed", "carrier"]),
        ("delivery", ["delivered", "delivery confirmed"]),
        ("policy", ["policy", "violation", "warning", "account health", "performance notification"]),
        ("stock_decrement", ["order", "sale", "sold", "transaction", "paid", "purchase"]),
    ]

    for label, words in checks:
        if any(word in combined for word in words):
            return label

    return "marketplace_notification"


def _business_reason(business_event: str) -> str:
    reasons = {
        "fba_pending": "FBA pending notification stored. No warehouse stock change is made until confirmed by later sync/received/adjustment state.",
        "fba_received": "FBA received notification stored for verification by light/full sync.",
        "fba_adjustment": "FBA adjustment notification stored for verification by light/full sync.",
        "fba_lost": "FBA lost notification stored for verification by light/full sync.",
        "fba_damaged": "FBA damaged notification stored for verification by light/full sync.",
        "fba_reimbursement": "FBA reimbursement notification stored for verification by light/full sync.",
        "customer_message": "Customer message notification stored for Step 1 awareness.",
        "return": "Return notification stored for Step 1 awareness.",
        "case": "Case/dispute notification stored for Step 1 awareness.",
        "listing_created": "Listing-created notification stored for Step 1 awareness.",
        "listing_removed": "Listing removed/blocked/ended notification stored for Step 1 awareness.",
        "payout": "Payout notification stored for Step 1 awareness.",
        "payment_deferred": "Deferred/held payment notification stored for Step 1 awareness.",
        "tracking": "Tracking notification stored for Step 1 awareness.",
        "delivery": "Delivery notification stored for Step 1 awareness.",
        "policy": "Policy/account-health notification stored for Step 1 awareness.",
    }
    return reasons.get(
        business_event,
        "Notification stored but did not contain a confirmed stock-decrement event.",
    )


def _is_stock_decrement_event(event_type: str, payload: dict) -> bool:
    return _classify_business_event(event_type, payload) == "stock_decrement"


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

    success_statuses = {
        "group_processed",
        "warehouse_processed",
        "stock_decrement_stored",
        "marketplace_notification_stored",
        "customer_message_stored",
        "return_stored",
        "case_stored",
        "listing_created_stored",
        "listing_removed_stored",
        "payout_stored",
        "payment_deferred_stored",
        "tracking_stored",
        "delivery_stored",
        "policy_stored",
        "fba_pending_stored",
        "fba_received_stored",
        "fba_adjustment_stored",
        "fba_lost_stored",
        "fba_damaged_stored",
        "fba_reimbursement_stored",
    }

    return {
        "ok": safe.get("status") in success_statuses,
        "success": safe.get("status") in success_statuses,
        "governed": True,
        **safe,
    }
