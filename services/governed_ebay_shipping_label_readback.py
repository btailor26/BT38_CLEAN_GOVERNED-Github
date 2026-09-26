"""Persist exact eBay label-purchase and fulfillment identity into existing FBMShipment.

The existing exact eBay hydration owns the Fulfillment API read and the existing
Finances reader owns monetary SHIPPING_LABEL truth. This module joins those two
already-governed facts for one exact order. It never infers a carrier from a
tracking number and it never creates an order, marketplace write, worker or
poller.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import xml.etree.ElementTree as ET

import requests
from sqlalchemy import text

from extensions import db
from fbm_models import FBMShipment
from fbm_tracking_event_models import FBMShipmentTrackingEvent
from models import MarketplaceOrder
from services.governed_exact_ebay_order_hydration import (
    _fulfillment_line_ids,
    _fulfillment_truth,
    _fulfillment_values,
)
from services.governed_marketplace_order_import import _ebay_access_token, _parse_ebay_datetime, _text


EBAY_TRADING_URL = "https://api.ebay.com/ws/api.dll"
EBAY_TRADING_COMPAT_LEVEL = "1193"
EBAY_TRADING_SITE_ID = "3"


def _fulfillment_id(value: dict[str, Any]) -> str:
    return _text(
        value.get("fulfillmentId")
        or value.get("shippingFulfillmentId")
        or value.get("shipmentId")
    )


def _service_value(value: dict[str, Any]) -> str:
    return _text(
        value.get("shippingServiceCode")
        or value.get("shippingServiceName")
        or value.get("service")
    )


def _trading_shipment_truth(*, access_token: str, order_id: str) -> dict[str, Any] | None:
    """Read exact-order carrier/tracking/delivery truth from eBay Trading GetOrders."""
    root = ET.Element("GetOrdersRequest", xmlns="urn:ebay:apis:eBLBaseComponents")
    credentials = ET.SubElement(root, "RequesterCredentials")
    ET.SubElement(credentials, "eBayAuthToken").text = access_token
    order_ids = ET.SubElement(root, "OrderIDArray")
    ET.SubElement(order_ids, "OrderID").text = order_id
    ET.SubElement(root, "OrderRole").text = "Seller"
    ET.SubElement(root, "DetailLevel").text = "ReturnAll"

    response = requests.post(
        EBAY_TRADING_URL,
        headers={
            "X-EBAY-API-CALL-NAME": "GetOrders",
            "X-EBAY-API-SITEID": EBAY_TRADING_SITE_ID,
            "X-EBAY-API-COMPATIBILITY-LEVEL": EBAY_TRADING_COMPAT_LEVEL,
            "X-EBAY-API-IAF-TOKEN": access_token,
            "Content-Type": "text/xml",
        },
        data=ET.tostring(root, encoding="utf-8", xml_declaration=True),
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"ebay_trading_get_orders_failed:{response.status_code}")

    parsed = ET.fromstring(response.content)
    if _text(parsed.findtext(".//{*}Ack")).upper() not in {"SUCCESS", "WARNING"}:
        error = parsed.find(".//{*}Errors")
        code = _text(error.findtext("{*}ErrorCode")) if error is not None else ""
        raise RuntimeError(f"ebay_trading_get_orders_failed:{code or 'ack'}")

    order = parsed.find(".//{*}Order")
    if order is None or _text(order.findtext("{*}OrderID")) != order_id:
        return None

    tracking_rows: list[dict[str, Any]] = []
    for detail in order.findall(".//{*}ShipmentTrackingDetails"):
        tracking = _text(detail.findtext("{*}ShipmentTrackingNumber"))
        if not tracking:
            continue
        tracking_rows.append({
            "tracking_number": tracking,
            "carrier": _text(detail.findtext("{*}ShippingCarrierUsed")) or None,
        })

    delivered_at = _parse_ebay_datetime(
        order.findtext(".//{*}ShippingPackageInfo/{*}ActualDeliveryTime")
    )
    # Trading GetOrders remains useful for historical eBay Shipping records
    # after Sell Fulfillment no longer returns shippedDate.  Keep this exact
    # order-level marketplace timestamp as a fallback factual shipped event;
    # never derive it from label purchase time or a tracking-number prefix.
    shipped_at = _parse_ebay_datetime(order.findtext("{*}ShippedTime"))
    if shipped_at is None:
        shipped_at = _parse_ebay_datetime(order.findtext(".//{*}Transaction/{*}ShippedTime"))

    # Keep the exact eBay line identity needed by the already-proven
    # tracking-details source.  These are authoritative GetOrders fields; no
    # tracking-prefix/carrier inference and no new persistence schema.
    line_identities: list[dict[str, str]] = []
    for transaction in order.findall(".//{*}Transaction"):
        item_id = _text(transaction.findtext("{*}Item/{*}ItemID"))
        transaction_id = _text(transaction.findtext("{*}TransactionID"))
        order_line_item_id = _text(transaction.findtext("{*}OrderLineItemID"))
        if not item_id or not transaction_id:
            continue
        line_identities.append({
            "item_id": item_id,
            "transaction_id": transaction_id,
            "order_line_item_id": order_line_item_id,
        })

    return {
        "tracking_rows": tracking_rows,
        "shipped_at": shipped_at,
        "delivered_at": delivered_at,
        "line_identities": line_identities,
    }


def _confirmed_finance_purchase(*, store_id: int, order_id: str) -> dict[str, Any] | None:
    """Return exact-order eBay label spend only when a debit is confirmed."""
    row = db.session.execute(
        text(
            """
            SELECT MIN(recorded_at) AS purchased_at,
                   COUNT(*) AS purchase_rows,
                   MIN(currency) AS currency,
                   SUM(ABS(amount)) AS amount
            FROM shipping_spend_ledger
            WHERE store_id = :store_id
              AND marketplace_order_id = :order_id
              AND fulfillment_family = 'FBM'
              AND provider = 'ebay'
              AND source = 'ebay_finances_shipping_label'
              AND confirmed = TRUE
            """
        ),
        {"store_id": int(store_id), "order_id": order_id},
    ).mappings().first()
    if not row or int(row.get("purchase_rows") or 0) < 1 or row.get("purchased_at") is None:
        return None
    return dict(row)


def _unique_fulfillment_candidates(fulfillments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate payload rows by durable fulfillment id only."""
    candidates: dict[str, dict[str, Any]] = {}
    conflicted_ids: set[str] = set()
    for fulfillment in fulfillments:
        fulfillment_id = _fulfillment_id(fulfillment)
        if not fulfillment_id or fulfillment_id in conflicted_ids:
            continue
        values = _fulfillment_values(fulfillment)
        candidate = {
            "fulfillment_id": fulfillment_id,
            "carrier": values.get("carrier") or None,
            "tracking_number": values.get("tracking_number") or None,
            "shipped_at": values.get("shipped_at"),
            "service": _service_value(fulfillment) or None,
            "line_item_ids": sorted(_fulfillment_line_ids(fulfillment)),
        }
        existing = candidates.get(fulfillment_id)
        if existing is None:
            candidates[fulfillment_id] = candidate
            continue
        for key in ("carrier", "tracking_number", "service"):
            if existing.get(key) and candidate.get(key) and existing[key] != candidate[key]:
                candidates.pop(fulfillment_id, None)
                conflicted_ids.add(fulfillment_id)
                break
        else:
            if not existing.get("carrier"):
                existing["carrier"] = candidate.get("carrier")
            if not existing.get("tracking_number"):
                existing["tracking_number"] = candidate.get("tracking_number")
            if not existing.get("service"):
                existing["service"] = candidate.get("service")
            if existing.get("shipped_at") is None:
                existing["shipped_at"] = candidate.get("shipped_at")
            existing["line_item_ids"] = sorted(set(existing["line_item_ids"]) | set(candidate["line_item_ids"]))
    return list(candidates.values())


def _persist_ebay_known_tracking_events(*, shipment: FBMShipment, candidate: dict[str, Any], delivered_at: datetime | None) -> int:
    """Persist only shipment events eBay exposes through supported order APIs.

    This deliberately does not invent carrier acceptance or in-transit scans.
    Sell Fulfillment shippedDate and Trading ActualDeliveryTime are eBay-owned
    facts; richer carrier scan history remains separate until eBay exposes a
    supported outbound tracking-history read.
    """
    events: list[dict[str, Any]] = []
    shipped_at = candidate.get("shipped_at")
    shipped_source = "ebay_sell_fulfillment"
    shipped_field = "shippedDate"
    if shipped_at is None and candidate.get("trading_shipped_at") is not None:
        shipped_at = candidate.get("trading_shipped_at")
        shipped_source = "ebay_trading_get_orders"
        shipped_field = "ShippedTime"
    if shipped_at is not None:
        events.append({
            "event_key": f"ebay:fulfillment:{candidate.get('fulfillment_id')}:shipped:{shipped_at.isoformat()}",
            "event_time": shipped_at,
            "status": "shipped",
            "description": "Shipment marked shipped by eBay",
            "detail": None,
            "raw_event": {
                "source": shipped_source,
                "field": shipped_field,
                "fulfillment_id": candidate.get("fulfillment_id"),
                "tracking_number": candidate.get("tracking_number"),
            },
        })
    if delivered_at is not None:
        events.append({
            "event_key": f"ebay:trading:{candidate.get('tracking_number')}:delivered:{delivered_at.isoformat()}",
            "event_time": delivered_at,
            "status": "delivered",
            "description": "Delivered",
            "detail": None,
            "raw_event": {
                "source": "ebay_trading_get_orders",
                "field": "ActualDeliveryTime",
                "tracking_number": candidate.get("tracking_number"),
            },
        })

    inserted = 0
    for event in events:
        exists = FBMShipmentTrackingEvent.query.filter_by(
            shipment_id=shipment.id,
            event_key=event["event_key"],
        ).first()
        if exists is not None:
            continue
        db.session.add(FBMShipmentTrackingEvent(
            shipment_id=shipment.id,
            provider="ebay",
            event_key=event["event_key"],
            event_time=event["event_time"],
            status=event["status"],
            description=event["description"],
            detail=event["detail"],
            raw_event=event["raw_event"],
            observed_at=datetime.utcnow(),
        ))
        inserted += 1
    return inserted


def persist_exact_ebay_purchased_shipment_authority(*, store, marketplace_order_id: str) -> dict[str, Any]:
    """Join exact eBay finance purchase proof to exact fulfillment identity.

    Exactly one durable fulfillment id is required. Multiple physical
    fulfillments are never collapsed into an invented order-level shipment.
    Tracking remains optional; fulfillmentId is the durable shipment identity.
    """
    order_id = _text(marketplace_order_id)
    if not order_id:
        return {"success": False, "skipped": True, "reason": "ebay_order_id_missing"}

    rows = (
        MarketplaceOrder.query
        .filter(
            MarketplaceOrder.store_id == store.id,
            MarketplaceOrder.marketplace_order_id == order_id,
        )
        .order_by(MarketplaceOrder.id.asc())
        .all()
    )
    if not rows:
        return {"success": False, "skipped": True, "reason": "existing_marketplace_order_missing", "order_id": order_id}

    # Shipment/tracking authority is independent from label-cost authority.
    # Finance may be unavailable for historical/external labels; never let that
    # suppress exact eBay fulfillment persistence or invent a £0 purchase.
    purchase = _confirmed_finance_purchase(store_id=store.id, order_id=order_id)

    try:
        access_token = _ebay_access_token(store)
        fulfillments, fulfillment_error = _fulfillment_truth(access_token=access_token, order_id=order_id)
    except Exception as exc:
        return {"success": False, "skipped": False, "reason": f"ebay_fulfillment_read_failed:{exc}", "order_id": order_id}

    if fulfillment_error:
        return {"success": False, "skipped": False, "reason": fulfillment_error, "order_id": order_id}

    try:
        trading_truth = _trading_shipment_truth(access_token=access_token, order_id=order_id)
    except Exception as exc:
        return {
            "success": False,
            "skipped": False,
            "reason": f"ebay_trading_read_failed:{exc}",
            "order_id": order_id,
        }

    candidates = _unique_fulfillment_candidates(fulfillments)
    if len(candidates) != 1:
        return {
            "success": False,
            "skipped": True,
            "reason": "ebay_fulfillment_ambiguous" if candidates else "ebay_fulfillment_identity_missing",
            "order_id": order_id,
            "fulfillments_seen": len(fulfillments),
            "candidate_count": len(candidates),
        }

    candidate = candidates[0]
    fulfillment_id = candidate["fulfillment_id"]
    shipment = FBMShipment.query.filter_by(
        store_id=store.id,
        marketplace_order_id=order_id,
        provider="ebay_shipping",
        provider_shipment_id=fulfillment_id,
    ).first()
    created = shipment is None
    if shipment is None:
        shipment = FBMShipment(
            store_id=store.id,
            marketplace_order_id=order_id,
            provider="ebay_shipping",
            provider_shipment_id=fulfillment_id,
            purchase_key=f"ebay_shipping_readback:{store.id}:{order_id}:{fulfillment_id}"[:200],
        )
        db.session.add(shipment)

    shipment.provider = "ebay_shipping"
    shipment.provider_shipment_id = fulfillment_id
    shipment.service = candidate.get("service") or shipment.service
    shipment.tracking_number = candidate.get("tracking_number") or shipment.tracking_number

    trading_match = None
    if trading_truth and shipment.tracking_number:
        matches = [
            row for row in trading_truth.get("tracking_rows", [])
            if row.get("tracking_number") == shipment.tracking_number
        ]
        if len(matches) == 1:
            trading_match = matches[0]

    if trading_match and trading_match.get("carrier"):
        shipment.carrier = trading_match["carrier"]

    # Older completed fulfillments can omit shippedDate from Sell Fulfillment
    # while Trading GetOrders still exposes the exact order ShippedTime.
    # Attach it only to this already-unambiguous physical fulfillment candidate.
    if trading_truth and trading_match and candidate.get("shipped_at") is None:
        candidate["trading_shipped_at"] = trading_truth.get("shipped_at")

    if purchase is not None:
        shipment.purchase_status = "purchased"
        shipment.purchase_error = None
        shipment.label_purchased_at = purchase["purchased_at"]
        shipment.label_source = "ebay_finances_shipping_label"
    delivered_at = trading_truth.get("delivered_at") if trading_truth and trading_match else None
    if delivered_at is not None:
        shipment.delivered_at = delivered_at
        shipment.status = "delivered"
        shipment.last_provider_status = "delivered"
    elif shipment.delivered_at is None:
        if shipment.status not in {"carrier_accepted", "in_transit", "out_for_delivery", "delivered"}:
            shipment.status = "shipped" if shipment.tracking_number else ("label_purchased" if purchase is not None else "shipped")
        if _text(shipment.last_provider_status).lower() != "delivered":
            shipment.last_provider_status = "shipped"
    shipment.last_provider_checked_at = datetime.utcnow()
    shipment.marketplace_confirmation_status = "ebay_shipping_fulfillment_readback"

    db.session.flush()

    # Keep the governed shipment/order relationship durable even when finance
    # proof is unavailable. Replay-safe on the existing unique identity.
    now = datetime.utcnow()
    db.session.execute(
        text(
            """
            INSERT INTO fbm_shipment_order_links (
                shipment_id, store_id, marketplace_order_id, is_primary,
                marketplace_confirmed_at, marketplace_confirmation_status,
                marketplace_confirmation_error, created_at, updated_at
            ) VALUES (
                :shipment_id, :store_id, :order_id, TRUE,
                :confirmed_at, 'ebay_shipping_fulfillment_readback',
                NULL, :created_at, :updated_at
            )
            ON CONFLICT (shipment_id, store_id, marketplace_order_id)
            DO UPDATE SET
                marketplace_confirmed_at = EXCLUDED.marketplace_confirmed_at,
                marketplace_confirmation_status = EXCLUDED.marketplace_confirmation_status,
                marketplace_confirmation_error = NULL,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {
            "shipment_id": shipment.id,
            "store_id": int(store.id),
            "order_id": order_id,
            "confirmed_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )

    tracking_events_inserted = _persist_ebay_known_tracking_events(
        shipment=shipment,
        candidate=candidate,
        delivered_at=delivered_at,
    )
    if purchase is not None:
        db.session.execute(
            text(
                """
            UPDATE shipping_spend_ledger
            SET shipment_id = :shipment_id,
                updated_at = :updated_at
            WHERE store_id = :store_id
              AND marketplace_order_id = :order_id
              AND provider = 'ebay'
              AND source = 'ebay_finances_shipping_label'
              AND confirmed = TRUE
              AND (shipment_id IS NULL OR shipment_id = :shipment_id)
                """
            ),
            {
                "shipment_id": shipment.id,
                "updated_at": datetime.utcnow(),
                "store_id": int(store.id),
                "order_id": order_id,
            },
        )
    db.session.commit()

    return {
        "success": True,
        "skipped": False,
        "order_id": order_id,
        "shipment_id": shipment.id,
        "provider": "ebay_shipping",
        "provider_shipment_id": fulfillment_id,
        "carrier": shipment.carrier,
        "service": shipment.service,
        "tracking_number": shipment.tracking_number,
        "delivered_at": shipment.delivered_at.isoformat() if shipment.delivered_at else None,
        "trading_truth_matched": bool(trading_match),
        "purchase_confirmed": purchase is not None,
        "shipping_cost_persisted": purchase is not None,
        "shipping_cost": float(purchase["amount"]) if purchase is not None and purchase.get("amount") is not None else None,
        "shipping_cost_currency": str(purchase.get("currency") or "") if purchase is not None else None,
        "shipping_cost_records": int(purchase.get("purchase_rows") or 0) if purchase is not None else 0,
        "created": created,
        "tracking_events_inserted": tracking_events_inserted,
        "marketplace_write_started": False,
    }
