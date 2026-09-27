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
    shipment_id = shipment.get("id")

    event_count = 0
    if shipment_id is not None:
        event_count = int(db.session.execute(
            text("SELECT COUNT(id) FROM fbm_shipment_tracking_events WHERE shipment_id = :shipment_id"),
            {"shipment_id": int(shipment_id)},
        ).scalar() or 0)

    provider = str(shipment.get("provider") or "").strip().lower()
    provider_ref = shipment.get("provider_shipment_id")
    tracking = readback.get("tracking_number") or shipment.get("tracking_number")
    carrier = shipment.get("carrier") or readback.get("carrier")
    spend = readback.get("confirmed_shipping_spend")

    fields = {
        "tracking_number": _field("known", tracking, authority="database") if tracking else _field("missing"),
        "carrier": _field("known", carrier, authority="database") if carrier else _field("missing"),
        "shipping_source": (
            _field("known", provider, authority="fbm_shipments")
            if provider and provider != "marketplace"
            else _field("unverified", provider or None, authority="fbm_shipments" if provider else None)
        ),
        "provider_reference": _field("known", provider_ref, authority="fbm_shipments") if provider_ref else _field("missing"),
        "tracking_history": _field("known", event_count, authority="fbm_shipment_tracking_events") if event_count else _field("missing", 0),
        "shipping_fee": _field("known", spend, authority="shipping_spend_ledger") if spend else _field("missing"),
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
