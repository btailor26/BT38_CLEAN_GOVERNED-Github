"""Canonical DB-derived FBM Data Truth Review.

This module classifies persisted facts only. It never contacts a marketplace,
carrier or shipping provider and never mutates the database. Recovery consumes
this review; it must not invent its own definition of what is missing.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from extensions import db


_STATES = {"known", "missing", "unverified", "unavailable", "not_applicable"}


def _field(state: str, value: Any = None, *, authority: str | None = None) -> dict[str, Any]:
    if state not in _STATES:
        raise ValueError(f"invalid truth state: {state}")
    return {"state": state, "value": value, "authority": authority}


def review_fbm_data_truth(*, store_id: int, order_id: str, platform: str, readback: dict[str, Any]) -> dict[str, Any]:
    """Return one structured truth/gap manifest from persisted DB facts only."""
    shipment = dict(readback.get("fbm_shipment") or {})
    mcf = dict(readback.get("mcf_order") or {})
    shipment_id = shipment.get("id")

    event_count = 0
    if shipment_id is not None:
        event_count = int(db.session.execute(
            text("SELECT COUNT(id) FROM fbm_shipment_tracking_events WHERE shipment_id = :shipment_id"),
            {"shipment_id": int(shipment_id)},
        ).scalar() or 0)

    provider = str(shipment.get("provider") or "").strip().lower()
    provider_ref = shipment.get("provider_shipment_id")
    is_mcf = bool(mcf.get("id"))
    tracking = (mcf.get("tracking_number") if is_mcf else None) or shipment.get("tracking_number") or readback.get("tracking_number")
    carrier = (mcf.get("carrier") if is_mcf else None) or shipment.get("carrier") or readback.get("carrier")
    spend = readback.get("confirmed_shipping_spend")
    mcf_fee = mcf.get("total_mcf_fee") if is_mcf else None
    shipping_source = "amazon_mcf" if is_mcf else provider
    source_authority = "mcf_orders" if is_mcf else ("fbm_shipments" if provider else None)
    tracking_authority = "mcf_orders" if is_mcf and mcf.get("tracking_number") else ("fbm_shipments" if shipment.get("tracking_number") else "marketplace_orders")
    carrier_authority = "mcf_orders" if is_mcf and mcf.get("carrier") else ("fbm_shipments" if shipment.get("carrier") else "marketplace_orders")

    fields = {
        # Mirror the current FBM row template. Any absent display fact is a gap/red flag.
        "marketplace": _field("known", readback.get("marketplace"), authority="stores") if readback.get("marketplace") else _field("missing"),
        "store_name": _field("known", readback.get("store_name"), authority="stores") if readback.get("store_name") else _field("missing"),
        "marketplace_order_id": _field("known", readback.get("marketplace_order_id"), authority="marketplace_orders") if readback.get("marketplace_order_id") else _field("missing"),
        "order_created_at": _field("known", readback.get("order_created_at"), authority="marketplace_orders") if readback.get("order_created_at") is not None else _field("missing"),
        "product_name": _field("known", readback.get("product_name"), authority="warehouse_stock") if readback.get("product_name") else _field("missing"),
        "sku": _field("known", readback.get("sku"), authority="marketplace_orders") if readback.get("sku") else _field("missing"),
        "quantity": _field("known", readback.get("quantity"), authority="marketplace_orders") if readback.get("quantity") is not None else _field("missing"),
        "fulfillment_type": _field("known", readback.get("fulfillment_type"), authority="marketplace_orders") if readback.get("fulfillment_type") else _field("missing"),
        "tracking_number": _field("known", tracking, authority=tracking_authority) if tracking else _field("missing"),
        "carrier": _field("known", carrier, authority=carrier_authority) if carrier else _field("missing"),
        "shipping_source": (
            _field("known", shipping_source, authority=source_authority)
            if is_mcf or (provider and provider != "marketplace")
            else _field("unverified", provider or None, authority="fbm_shipments" if provider else None)
        ),
        "provider_reference": (
            _field("known", mcf.get("seller_fulfillment_order_id"), authority="mcf_orders")
            if is_mcf and mcf.get("seller_fulfillment_order_id")
            else (_field("known", provider_ref, authority="fbm_shipments") if provider_ref else _field("missing"))
        ),
        "tracking_history": _field("known", event_count, authority="fbm_shipment_tracking_events") if event_count else _field("missing", 0),
        "shipping_fee": (
            _field("known", {"amount": mcf_fee, "currency": mcf.get("currency") or "GBP"}, authority="mcf_orders")
            if mcf_fee is not None
            else (_field("known", spend, authority="shipping_spend_ledger") if spend else _field("missing"))
        ),
        "ship_by_promise": _field("known", readback.get("ship_by_at"), authority="fbm_order_operational_state") if readback.get("ship_by_at") is not None else _field("missing"),
        "delivery_promise": (
            _field(
                "known",
                {"earliest": readback.get("earliest_delivery_at"), "latest": readback.get("latest_delivery_at")},
                authority="fbm_order_operational_state",
            )
            if readback.get("earliest_delivery_at") is not None or readback.get("latest_delivery_at") is not None
            else _field("missing")
        ),
    }

    gaps = [
        {"field": name, **fact}
        for name, fact in fields.items()
        if fact["state"] in {"missing", "unverified"}
    ]
    return {
        "store_id": int(store_id),
        "order_id": str(order_id),
        "platform": str(platform).strip().lower(),
        "db_authority": True,
        "external_call_started": False,
        "fields": fields,
        "gaps": gaps,
        "missing": [gap["field"] for gap in gaps if gap["state"] == "missing"],
        "unverified": [gap["field"] for gap in gaps if gap["state"] == "unverified"],
        "recovery_required": bool(gaps),
    }
