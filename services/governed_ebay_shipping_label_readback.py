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
    return {
        "tracking_rows": tracking_rows,
        "delivered_at": delivered_at,
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

    purchase = _confirmed_finance_purchase(store_id=store.id, order_id=order_id)
    if purchase is None:
        return {"success": False, "skipped": True, "reason": "ebay_shipping_label_purchase_not_confirmed", "order_id": order_id}

    try:
        access_token = _ebay_access_token(store)
        fulfillments, fulfillment_error = _fulfillment_truth(access_token=access_token, order_id=order_id)
    except Exception as exc:
        return {"success": False, "skipped": False, "reason": f"ebay_fulfillment_read_failed:{exc}", "order_id": order_id}

    if fulfillment_error:
        return {"success": False, "skipped": False, "reason": fulfillment_error, "order_id": order_id}

    try:
        trading_truth = _trading_shipment_truth(access_token=access_token, order_id=order_id)
    except Exception:
        trading_truth = None

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
            shipment.status = "awaiting_carrier_acceptance" if shipment.tracking_number else "label_purchased"
        if _text(shipment.last_provider_status).lower() != "delivered":
            shipment.last_provider_status = "shipped"
    shipment.last_provider_checked_at = datetime.utcnow()
    shipment.marketplace_confirmation_status = "ebay_shipping_fulfillment_readback"

    db.session.flush()
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
        "purchase_confirmed": True,
        "created": created,
        "marketplace_write_started": False,
    }
