"""Recover exact Royal Mail Click & Drop label authority into FBMShipment.

This is an explicit, exact-order readback. MarketplaceOrder remains the sale
record and FBMShipment remains the only physical shipment store. No background
scan, order import, postage purchase, inventory mutation or marketplace write.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from extensions import db
from fbm_models import FBMShipment
from models import MarketplaceOrder, Store
from shipping_spend_models import ShippingSpendLedger
from services.royal_mail_click_drop import RoyalMailClickDropClient


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_iso(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _tracking(order: dict[str, Any], detail: dict[str, Any]) -> str:
    shipping = detail.get("shippingDetails") if isinstance(detail.get("shippingDetails"), dict) else {}
    direct = _text(shipping.get("trackingNumber") or order.get("trackingNumber"))
    if direct:
        return direct
    for source in (shipping.get("packages"), order.get("packages")):
        if not isinstance(source, list):
            continue
        for package in source:
            if isinstance(package, dict) and _text(package.get("trackingNumber")):
                return _text(package.get("trackingNumber"))
    return ""


def _confirmed_cost(detail: dict[str, Any]) -> Decimal | None:
    """Use Royal Mail shippingCost only when detailed postage evidence exists."""
    shipping = detail.get("shippingDetails") if isinstance(detail.get("shippingDetails"), dict) else {}
    if not _parse_iso(detail.get("postageAppliedOn")):
        return None
    raw = shipping.get("shippingCost")
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value >= 0 else None


def _persist_spend(shipment: FBMShipment, detail: dict[str, Any]) -> ShippingSpendLedger | None:
    amount = _confirmed_cost(detail)
    if amount is None:
        return None
    dispatch_key = shipment.purchase_key or f"royal_mail_click_drop:{shipment.store_id}:{shipment.provider_shipment_id}"
    row = ShippingSpendLedger.query.filter_by(dispatch_key=dispatch_key).first()
    if row is None:
        row = ShippingSpendLedger(dispatch_key=dispatch_key)
        db.session.add(row)
    row.shipment_id = shipment.id
    row.store_id = shipment.store_id
    row.marketplace_order_id = shipment.marketplace_order_id
    row.fulfillment_family = "FBM"
    row.provider = "royal_mail_click_drop"
    row.amount = amount
    row.currency = _text(detail.get("currencyCode"))[:3].upper() or "GBP"
    row.source = "royal_mail_click_drop_postage_applied"
    row.source_reference = shipment.provider_shipment_id
    row.confirmed = True
    row.recorded_at = _parse_iso(detail.get("postageAppliedOn")) or datetime.utcnow()
    return row


def hydrate_royal_mail_label_for_order(*, store_id: int, marketplace_order_id: str, api_key: str) -> dict[str, Any]:
    order_id = _text(marketplace_order_id)
    store = db.session.get(Store, int(store_id))
    if store is None or not order_id:
        return {"success": False, "skipped": True, "reason": "existing_marketplace_order_missing"}

    marketplace_rows = MarketplaceOrder.query.filter_by(store_id=store.id, marketplace_order_id=order_id).all()
    if not marketplace_rows:
        return {"success": False, "skipped": True, "reason": "existing_marketplace_order_missing"}

    evidence = RoyalMailClickDropClient(api_key=api_key).get_exact_order_evidence(order_id)
    orders = evidence.get("orders") or []
    if not orders:
        return {
            "success": True, "skipped": True, "reason": "royal_mail_exact_order_not_found",
            "order_id": order_id, "marketplace_write_started": False, "broad_scan_started": False,
        }

    order = next((row for row in orders if _text(row.get("orderReference")) == order_id), orders[0])
    details = evidence.get("details") or []
    detail = next((row for row in details if _text(row.get("orderReference")) == order_id), details[0] if details else {})
    provider_id = _text(order.get("orderIdentifier") or detail.get("orderIdentifier"))
    tracking = _tracking(order, detail)
    printed_at = _parse_iso(detail.get("printedOn") or order.get("printedOn"))
    postage_at = _parse_iso(detail.get("postageAppliedOn"))
    shipped_at = _parse_iso(detail.get("shippedOn") or order.get("shippedOn"))
    manifested_at = _parse_iso(detail.get("manifestedOn") or order.get("manifestedOn"))
    label_proven = bool(provider_id and (printed_at or postage_at or tracking or shipped_at or manifested_at))
    if not label_proven:
        return {
            "success": True, "skipped": True, "reason": "royal_mail_label_not_yet_proven",
            "order_id": order_id, "provider_order_id": provider_id or None,
            "marketplace_write_started": False, "broad_scan_started": False,
        }

    shipment = None
    if provider_id:
        shipment = FBMShipment.query.filter_by(
            store_id=store.id, provider="royal_mail_click_drop", provider_shipment_id=provider_id
        ).order_by(FBMShipment.id.desc()).first()
    if shipment is None:
        shipment = FBMShipment(
            store_id=store.id,
            marketplace_order_id=order_id,
            provider="royal_mail_click_drop",
            provider_shipment_id=provider_id or f"order:{order_id}",
            purchase_key=f"royal_mail_click_drop_recovered:{store.id}:{provider_id or order_id}",
        )
        db.session.add(shipment)

    shipping = detail.get("shippingDetails") if isinstance(detail.get("shippingDetails"), dict) else {}
    carrier = _text(shipping.get("shippingCarrier")) or "Royal Mail"
    service = _text(shipping.get("shippingService"))
    service_code = _text(shipping.get("serviceCode"))

    shipment.marketplace_order_id = order_id
    shipment.provider = "royal_mail_click_drop"
    shipment.carrier = carrier
    shipment.provider_carrier_id = carrier
    if service:
        shipment.service = service
    if service_code:
        shipment.provider_service_id = service_code
    if tracking:
        shipment.tracking_number = tracking
    shipment.label_source = "royal_mail_click_drop"
    shipment.purchase_status = "purchased" if (postage_at or printed_at) else "label_confirmed"
    shipment.label_purchased_at = shipment.label_purchased_at or postage_at or printed_at
    shipment.last_provider_checked_at = datetime.utcnow()
    shipment.last_provider_status = _text(detail.get("orderStatus")) or ("shipped" if shipped_at else "label_confirmed")
    shipment.status = "shipped" if shipped_at else ("purchased" if shipment.purchase_status == "purchased" else "label_confirmed")

    for row in marketplace_rows:
        if tracking:
            row.tracking_number = tracking
        row.carrier = carrier
        if shipped_at and not getattr(row, "shipped_at", None):
            row.shipped_at = shipped_at
        row.updated_at = datetime.utcnow()

    db.session.flush()
    spend = _persist_spend(shipment, detail)
    db.session.commit()
    return {
        "success": True, "skipped": False, "reason": None, "order_id": order_id,
        "shipment_id": shipment.id, "provider_shipment_id": shipment.provider_shipment_id,
        "provider": shipment.provider, "carrier": shipment.carrier, "service": shipment.service,
        "tracking_number": shipment.tracking_number, "purchase_status": shipment.purchase_status,
        "shipping_cost": str(spend.amount) if spend is not None else None,
        "currency": spend.currency if spend is not None else None,
        "details_available": bool(evidence.get("details_available")),
        "marketplace_write_started": False, "label_purchase_started": False, "broad_scan_started": False,
    }
