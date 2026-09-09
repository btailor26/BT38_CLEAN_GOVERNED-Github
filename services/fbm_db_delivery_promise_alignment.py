"""DB-only FBM delivery-promise and delivery-performance projection.

Marketplace promises and carrier lifecycle timestamps are already persisted by
governed event/hydration paths. FBM presentation consumes those stored facts
for every carrier; rendering never reads a marketplace or carrier provider.
"""
from __future__ import annotations

from typing import Any

from flask import before_render_template, g
from sqlalchemy import bindparam, text, tuple_

from extensions import db
from fbm_models import FBMOrderProfile


_OPERATIONAL_FIELDS = (
    "shipping_service",
    "ship_by_at",
    "earliest_delivery_at",
    "latest_delivery_at",
)


def _profile_promises(keys: set[tuple[int, str]]) -> dict[tuple[int, str], dict[str, Any]]:
    if not keys:
        return {}
    identities = sorted(keys)
    rows = (
        db.session.query(FBMOrderProfile)
        .filter(tuple_(FBMOrderProfile.store_id, FBMOrderProfile.marketplace_order_id).in_(identities))
        .order_by(FBMOrderProfile.updated_at.desc(), FBMOrderProfile.id.desc())
        .all()
    )
    result: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        key = (int(row.store_id), str(row.marketplace_order_id))
        if key in result:
            continue
        result[key] = {
            "shipping_service": row.shipment_service_level,
            "ship_by_at": row.latest_ship_at,
            "earliest_delivery_at": None,
            "latest_delivery_at": None,
            "source": "fbm_order_profiles",
        }
    return result


def _operational_promises(keys: set[tuple[int, str]]) -> dict[tuple[int, str], dict[str, Any]]:
    if not keys:
        return {}
    try:
        available = {
            str(row[0])
            for row in db.session.execute(text("""
                SELECT column_name FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'fbm_order_operational_state'
            """)).all()
        }
    except Exception:
        db.session.rollback()
        return {}
    if not {"store_id", "marketplace_order_id"}.issubset(available):
        return {}
    store_ids = sorted({key[0] for key in keys})
    order_ids = sorted({key[1] for key in keys})
    select_fields = [field if field in available else f"NULL AS {field}" for field in _OPERATIONAL_FIELDS]
    statement = text(f"""
        SELECT store_id, marketplace_order_id, {', '.join(select_fields)}
          FROM fbm_order_operational_state
         WHERE store_id IN :store_ids AND marketplace_order_id IN :order_ids
    """).bindparams(bindparam("store_ids", expanding=True), bindparam("order_ids", expanding=True))
    try:
        rows = db.session.execute(statement, {"store_ids": store_ids, "order_ids": order_ids}).mappings().all()
    except Exception:
        db.session.rollback()
        return {}
    return {
        (int(row["store_id"]), str(row["marketplace_order_id"])): {
            "shipping_service": row["shipping_service"],
            "ship_by_at": row["ship_by_at"],
            "earliest_delivery_at": row["earliest_delivery_at"],
            "latest_delivery_at": row["latest_delivery_at"],
            "source": "fbm_order_operational_state",
        }
        for row in rows
        if (int(row["store_id"]), str(row["marketplace_order_id"])) in keys
    }


def _merge_promise(fallback: dict[str, Any] | None, operational: dict[str, Any] | None) -> dict[str, Any] | None:
    if fallback is None and operational is None:
        return None
    merged = dict(fallback or {})
    if operational:
        for field in _OPERATIONAL_FIELDS:
            value = operational.get(field)
            if value is not None:
                merged[field] = value
        merged["source"] = operational.get("source") or merged.get("source")
    return merged


def _delivery_performance(shipment: Any, promise: dict[str, Any] | None) -> str:
    """Return performance from persisted DB timestamps only, carrier-neutral."""
    delivered_at = getattr(shipment, "delivered_at", None) if shipment is not None else None
    latest_delivery_at = (promise or {}).get("latest_delivery_at")
    if delivered_at is None:
        return ""
    if latest_delivery_at is None:
        return "timing_unavailable"
    return "on_time" if delivered_at <= latest_delivery_at else "late"


def _shipping_source(shipment: Any) -> str:
    """Return only a persisted label-purchase source; never infer one."""
    if shipment is None:
        return ""
    provider = str(getattr(shipment, "provider", "") or "").strip().lower()
    label_source = str(getattr(shipment, "label_source", "") or "").strip().lower()
    if provider == "packlink" or label_source == "packlink":
        return "Packlink"
    if provider == "ebay_shipping" or label_source == "ebay_finances_shipping_label":
        return "eBay Shipping"
    if provider in {"amazon_buy_shipping", "amazon_shipping"} or label_source in {"amazon_buy_shipping", "amazon_shipping"}:
        return "Amazon Buy Shipping"
    return ""


def install_fbm_db_delivery_promise_alignment(app: Any) -> None:
    if getattr(app, "_bt38_fbm_db_delivery_promise_alignment", False):
        return
    from services.governed_amazon_fbm_profile_event_alignment import install_governed_amazon_fbm_profile_event_alignment
    install_governed_amazon_fbm_profile_event_alignment(app)

    @before_render_template.connect_via(app)
    def _inject_fbm_delivery_promises(sender, template, context, **extra):
        if getattr(template, "name", None) != "fbm.html":
            return
        items = context.get("orders") or []
        keys = {
            (int(getattr(item.get("order"), "store_id", 0) or 0), str(getattr(item.get("order"), "marketplace_order_id", "") or "").strip())
            for item in items if isinstance(item, dict) and item.get("order") is not None
        }
        keys = {key for key in keys if key[0] > 0 and key[1]}
        if not keys:
            return
        profile_promises = _profile_promises(keys)
        operational_promises = _operational_promises(keys)
        rendered_truth: dict[int, dict[str, str]] = {}

        for item in items:
            if not isinstance(item, dict):
                continue
            order = item.get("order")
            key = (int(getattr(order, "store_id", 0) or 0), str(getattr(order, "marketplace_order_id", "") or "").strip())
            promise = _merge_promise(profile_promises.get(key), operational_promises.get(key))
            item["delivery_promise"] = promise
            shipment = item.get("shipment")
            performance = _delivery_performance(shipment, promise)
            item["delivery_performance"] = performance
            order_id = int(getattr(order, "id", 0) or 0)
            if order_id:
                rendered_truth[order_id] = {
                    "shipment_state": str(item.get("shipment_state") or ""),
                    "delivered_at": getattr(shipment, "delivered_at", None).isoformat() if shipment is not None and getattr(shipment, "delivered_at", None) else "",
                    "ship_by_at": (promise or {}).get("ship_by_at").isoformat() if (promise or {}).get("ship_by_at") else "",
                    "latest_delivery_at": (promise or {}).get("latest_delivery_at").isoformat() if (promise or {}).get("latest_delivery_at") else "",
                    "delivery_performance": performance,
                    "shipping_source": _shipping_source(shipment),
                    "carrier": str((getattr(shipment, "carrier", "") if shipment is not None else "") or getattr(order, "carrier", "") or "").strip(),
                }

            provider = str(getattr(shipment, "provider", "") or "").strip().lower()
            service = str((promise or {}).get("shipping_service") or "").strip()
            platform = str(item.get("platform") or getattr(getattr(order, "store", None), "platform", "") or "").strip().lower()
            if shipment is not None and provider == "marketplace" and platform == "amazon" and service:
                shipment.service = service

        g.fbm_delivery_truth_by_order_id = rendered_truth

    app._bt38_fbm_db_delivery_promise_alignment = True
