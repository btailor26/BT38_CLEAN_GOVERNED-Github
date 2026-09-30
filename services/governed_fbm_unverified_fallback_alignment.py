"""Inline fallback completion for missing FBM truth.

This alignment does not create another shipment, spend, mapping or polling
authority. It lets an operator complete only a field that is still missing in
the existing persisted authorities. Provider/recovery truth remains stronger.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import jsonify, request
from flask_login import login_required
from sqlalchemy import text

from extensions import db
from fbm_models import FBMShipment
from models import MarketplaceOrder
from shipping_spend_models import ShippingSpendLedger


_SOURCE_LABELS = {
    "packlink": "Packlink",
    "amazon_shipping": "Amazon Shipping",
    "amazon_buy_shipping": "Amazon Buy Shipping",
    "ebay_finances_shipping_label": "eBay Shipping",
    "ebay_shipping": "eBay Shipping",
    "manual": "Manual",
}


def _normal(value) -> str:
    return str(value or "").strip()


def _source_key(value: str) -> str:
    raw = _normal(value)
    lowered = raw.lower().replace("-", " ").replace("_", " ")
    aliases = {
        "packlink": "packlink",
        "amazon shipping": "amazon_shipping",
        "amazon buy shipping": "amazon_buy_shipping",
        "ebay shipping": "ebay_finances_shipping_label",
        "manual": "manual",
    }
    return aliases.get(lowered, "_".join(lowered.split()))


def _source_label(value: str) -> str:
    key = _source_key(value)
    return _SOURCE_LABELS.get(key, key.replace("_", " ").title())


def _order(order_id: int) -> MarketplaceOrder | None:
    order = db.session.get(MarketplaceOrder, order_id)
    if order is None:
        return None
    fulfillment = _normal(getattr(order, "fulfillment_type", None)).upper()
    if fulfillment in {"FBA", "AFN", "MCF"}:
        return None
    return order


def _persisted_shipments(order: MarketplaceOrder) -> list[FBMShipment]:
    return (
        FBMShipment.query
        .filter_by(store_id=order.store_id, marketplace_order_id=order.marketplace_order_id)
        .order_by(FBMShipment.updated_at.desc(), FBMShipment.id.desc())
        .all()
    )


def _physical_source(shipments: list[FBMShipment]) -> str:
    for shipment in shipments:
        provider = _normal(shipment.provider).lower()
        label_source = _normal(shipment.label_source)
        if provider and provider != "marketplace":
            return label_source or provider
    return ""


def _fallback_shipment(order: MarketplaceOrder, shipments: list[FBMShipment]) -> FBMShipment:
    for shipment in shipments:
        if _normal(shipment.provider).lower() == "marketplace":
            return shipment
    shipment = FBMShipment(
        store_id=order.store_id,
        marketplace_order_id=order.marketplace_order_id,
        provider="marketplace",
        status=_normal(order.status).lower() or ("dispatched" if order.shipped_at else "awaiting_label"),
        marketplace_confirmed_at=order.shipped_at,
        marketplace_confirmation_status="marketplace_authoritative",
    )
    db.session.add(shipment)
    return shipment


def _automatic_spend_exists(order: MarketplaceOrder) -> bool:
    return (
        ShippingSpendLedger.query
        .filter_by(
            store_id=order.store_id,
            marketplace_order_id=order.marketplace_order_id,
            fulfillment_family="FBM",
            confirmed=True,
        )
        .filter(ShippingSpendLedger.source != "manual_fallback")
        .first()
        is not None
    )


def _manual_spend(order: MarketplaceOrder) -> ShippingSpendLedger | None:
    return ShippingSpendLedger.query.filter_by(
        dispatch_key=f"manual_fallback:{order.store_id}:{order.marketplace_order_id}"
    ).first()


def _source_options(order: MarketplaceOrder) -> list[str]:
    rows = db.session.execute(text("""
        SELECT DISTINCT COALESCE(NULLIF(label_source, ''), NULLIF(provider, '')) AS source
          FROM fbm_shipments
         WHERE COALESCE(NULLIF(label_source, ''), NULLIF(provider, '')) IS NOT NULL
           AND COALESCE(NULLIF(label_source, ''), NULLIF(provider, '')) <> 'marketplace'
         ORDER BY source
    """)).scalars().all()
    platform = _normal(getattr(getattr(order, "store", None), "platform", None)).lower()
    labels = {_source_label(value) for value in rows if _normal(value)}
    # Never offer a marketplace-native shipping source to the wrong marketplace.
    if platform == "amazon":
        labels = {label for label in labels if label != "eBay Shipping"}
    elif platform == "ebay":
        labels = {label for label in labels if label not in {"Amazon Shipping", "Amazon Buy Shipping"}}
    else:
        labels = {label for label in labels if label not in {"Amazon Shipping", "Amazon Buy Shipping", "eBay Shipping"}}
    return sorted(labels)


def _cost_options(order: MarketplaceOrder) -> list[float]:
    carrier = _normal(getattr(order, "carrier", None))
    rows = db.session.execute(text("""
        SELECT DISTINCT ssl.amount
          FROM shipping_spend_ledger ssl
          JOIN marketplace_orders mo
            ON mo.store_id = ssl.store_id
           AND mo.marketplace_order_id = ssl.marketplace_order_id
         WHERE ssl.confirmed = TRUE
           AND ssl.source <> 'manual_fallback'
           AND mo.sku = :sku
           AND COALESCE(mo.quantity, 1) = :quantity
           AND (:carrier = '' OR LOWER(COALESCE(mo.carrier, '')) = LOWER(:carrier))
         ORDER BY ssl.amount
    """), {
        "sku": _normal(getattr(order, "sku", None)),
        "quantity": max(1, int(getattr(order, "quantity", 1) or 1)),
        "carrier": carrier,
    }).scalars().all()
    return [float(value) for value in rows if value is not None]


def install_governed_fbm_unverified_fallback_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_unverified_fallback_alignment", False):
        return

    @login_required
    def unverified_options(order_id: int):
        order = _order(order_id)
        if order is None:
            return jsonify({"success": False, "message": "FBM order not found."}), 404
        field = _normal(request.args.get("field")).lower()
        if field == "source":
            return jsonify({"success": True, "field": field, "options": _source_options(order)})
        if field == "cost":
            return jsonify({
                "success": True,
                "field": field,
                "quantity": max(1, int(getattr(order, "quantity", 1) or 1)),
                "options": _cost_options(order),
            })
        if field == "tracking":
            return jsonify({"success": True, "field": field, "options": []})
        return jsonify({"success": False, "message": "Unsupported fallback field."}), 400

    @login_required
    def save_unverified_field(order_id: int):
        order = _order(order_id)
        if order is None:
            return jsonify({"success": False, "message": "FBM order not found."}), 404
        body = request.get_json(silent=True) or {}
        field = _normal(body.get("field")).lower()
        value = _normal(body.get("value"))
        carrier = _normal(body.get("carrier"))
        if not value:
            return jsonify({"success": False, "message": "A value is required."}), 400

        shipments = _persisted_shipments(order)

        if field == "source":
            if _physical_source(shipments):
                return jsonify({"success": False, "message": "Shipping source is already verified."}), 409
            shipment = _fallback_shipment(order, shipments)
            if _normal(shipment.label_source):
                return jsonify({"success": False, "message": "Shipping source is already supplied."}), 409
            shipment.label_source = _source_key(value)
            db.session.commit()
            return jsonify({
                "success": True,
                "field": field,
                "value": _source_label(shipment.label_source),
                "authority": "fbm_shipments.label_source",
            })

        if field == "cost":
            if _automatic_spend_exists(order):
                return jsonify({"success": False, "message": "Shipping cost is already verified."}), 409
            try:
                amount = Decimal(value).quantize(Decimal("0.0001"))
            except (InvalidOperation, ValueError):
                return jsonify({"success": False, "message": "Enter a valid shipping cost."}), 400
            if amount < 0:
                return jsonify({"success": False, "message": "Shipping cost cannot be negative."}), 400
            row = _manual_spend(order)
            if row is None:
                row = ShippingSpendLedger(
                    dispatch_key=f"manual_fallback:{order.store_id}:{order.marketplace_order_id}",
                    store_id=order.store_id,
                    marketplace_order_id=order.marketplace_order_id,
                    fulfillment_family="FBM",
                    provider="manual_fallback",
                    source="manual_fallback",
                    confirmed=True,
                )
                db.session.add(row)
            row.amount = amount
            row.currency = "GBP"
            row.recorded_at = row.recorded_at
            db.session.commit()
            return jsonify({
                "success": True,
                "field": field,
                "value": float(amount),
                "currency": "GBP",
                "authority": "shipping_spend_ledger",
            })

        if field == "carrier":
            # Carrier is an independent exact-order fact. Tracking may remain
            # NULL when the marketplace/provider has not supplied it.
            if _normal(getattr(order, "carrier", None)):
                return jsonify({"success": False, "message": "Carrier is already supplied."}), 409
            order.carrier = value
            db.session.commit()
            return jsonify({
                "success": True,
                "field": field,
                "value": value,
                "carrier": value,
                "tracking_number": _normal(getattr(order, "tracking_number", None)) or None,
                "authority": "marketplace_orders.carrier",
                "reusable_mapping": False,
            })

        if field == "tracking":
            if _normal(getattr(order, "tracking_number", None)):
                return jsonify({"success": False, "message": "Tracking is already supplied."}), 409
            if not carrier:
                return jsonify({"success": False, "message": "Carrier is required with a tracking number."}), 400
            # Carrier + tracking are one exact-order correction. They are never
            # a reusable product/SKU mapping and never copied to another order.
            order.carrier = carrier
            order.tracking_number = value
            db.session.commit()
            return jsonify({
                "success": True,
                "field": field,
                "value": value,
                "carrier": carrier,
                "authority": "marketplace_orders.carrier+tracking_number",
                "reusable_mapping": False,
            })

        return jsonify({"success": False, "message": "Unsupported fallback field."}), 400

    app.add_url_rule(
        "/fbm/orders/<int:order_id>/unverified-options",
        endpoint="bt38_fbm_unverified_options",
        view_func=unverified_options,
        methods=["GET"],
    )
    app.add_url_rule(
        "/fbm/orders/<int:order_id>/unverified-field",
        endpoint="bt38_fbm_unverified_field",
        view_func=save_unverified_field,
        methods=["POST"],
    )
    app._bt38_fbm_unverified_fallback_alignment = True
