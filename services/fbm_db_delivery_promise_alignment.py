"""DB-only FBM delivery-promise and delivery-performance projection.

Marketplace promises and carrier lifecycle timestamps are already persisted by
governed event/hydration paths. FBM presentation consumes those stored facts
for every carrier; rendering never reads a marketplace or carrier provider.
"""
from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo
from typing import Any

from flask import before_render_template, g
from sqlalchemy import bindparam, text, tuple_

from extensions import db
from fbm_models import FBMOrderProfile
from fbm_tracking_event_models import FBMShipmentTrackingEvent


_FBM_DISPLAY_TZ = ZoneInfo("Europe/London")

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


def _as_utc_aware(value: Any) -> Any:
    """Normalize a persisted datetime for comparison only; never mutate storage."""
    if value is None:
        return None
    tzinfo = getattr(value, "tzinfo", None)
    utcoffset = value.utcoffset() if tzinfo is not None else None
    if utcoffset is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_fbm_display_time(value: Any) -> Any:
    """Convert persisted UTC promise truth to Europe/London for presentation only."""
    if value is None:
        return None
    utc_value = _as_utc_aware(value)
    return utc_value.astimezone(_FBM_DISPLAY_TZ)


def _display_promise(promise: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a presentation copy; never mutate persisted marketplace promise values."""
    if promise is None:
        return None
    display = dict(promise)
    for field in ("ship_by_at", "earliest_delivery_at", "latest_delivery_at"):
        if display.get(field) is not None:
            display[field] = _as_fbm_display_time(display[field])
    return display


def _delivery_performance(shipment: Any, promise: dict[str, Any] | None) -> str:
    """Return performance from persisted DB timestamps only, carrier-neutral."""
    delivered_at = getattr(shipment, "delivered_at", None) if shipment is not None else None
    latest_delivery_at = (promise or {}).get("latest_delivery_at")
    if delivered_at is None:
        return ""
    if latest_delivery_at is None:
        return "timing_unavailable"
    delivered_cmp = _as_utc_aware(delivered_at)
    latest_delivery_cmp = _as_utc_aware(latest_delivery_at)
    return "on_time" if delivered_cmp <= latest_delivery_cmp else "late"


def _shipment_tracking_authority(shipment: Any, order: Any) -> dict[str, str]:
    """Resolve one carrier/tracking authority from persisted facts only.

    A shipment row may exist before a label/tracking identity is verified. Such a
    draft must never override an order that already has marketplace tracking.
    """
    shipment_tracking = str(getattr(shipment, "tracking_number", "") or "").strip() if shipment is not None else ""
    order_tracking = str(getattr(order, "tracking_number", "") or "").strip() if order is not None else ""
    if shipment_tracking:
        return {
            "carrier": str(getattr(shipment, "carrier", "") or "").strip(),
            "service": str(getattr(shipment, "service", "") or "").strip(),
            "tracking_number": shipment_tracking,
            "authority": "shipment",
        }
    if order_tracking:
        return {
            "carrier": str(getattr(order, "carrier", "") or "").strip(),
            "service": "",
            "tracking_number": order_tracking,
            "authority": "marketplace_order",
        }
    return {"carrier": "", "service": "", "tracking_number": "", "authority": ""}


def _shipping_source(shipment: Any) -> str:
    """Return only a persisted label-purchase source; never infer one."""
    if shipment is None:
        return ""
    provider = str(getattr(shipment, "provider", "") or "").strip().lower()
    label_source = str(getattr(shipment, "label_source", "") or "").strip().lower()
    if label_source == "packlink":
        return "Packlink"
    if label_source == "ebay_finances_shipping_label":
        return "eBay Shipping"
    if label_source in {"amazon_buy_shipping", "amazon_shipping"}:
        return "Amazon Buy Shipping"
    if provider in {"amazon_buy_shipping", "amazon_shipping"}:
        return "Amazon Buy Shipping"
    # Older verified shipment rows may pre-date label_source. Require a persisted
    # shipment identity before provider alone can identify the purchase source.
    has_shipment_identity = bool(
        str(getattr(shipment, "tracking_number", "") or "").strip()
        or str(getattr(shipment, "provider_shipment_id", "") or "").strip()
    )
    if has_shipment_identity and provider == "packlink":
        return "Packlink"
    if has_shipment_identity and provider == "ebay_shipping":
        return "eBay Shipping"
    if has_shipment_identity and provider in {"amazon_buy_shipping", "amazon_shipping"}:
        return "Amazon Buy Shipping"
    return ""


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else ""


def _is_pre_scan_event(event: dict[str, Any]) -> bool:
    """Exclude electronic pre-advice that occurs before physical carrier handling."""
    text_value = " ".join(
        str(event.get(field) or "").strip().lower()
        for field in ("status", "description", "detail")
    )
    pre_scan_markers = (
        "details received",
        "information received",
        "shipment information",
        "shipping information",
        "label created",
        "label generated",
        "label printed",
        "tracking number",
        "expecting your parcel",
        "expect your parcel",
        "expected in network",
        "pre-advice",
        "pre advice",
        "prealert",
        "pre-alert",
        "manifest created",
        "booking created",
    )
    return any(marker in text_value for marker in pre_scan_markers)


def _tracking_events(shipment_ids: set[int]) -> dict[int, list[dict[str, Any]]]:
    """Batch-read already-persisted carrier events for the visible canonical shipments.

    Journey pickup is carrier-neutral: once a label exists, the earliest genuine
    persisted carrier event is the pickup boundary. Provider wording is not part
    of that decision.
    """
    if not shipment_ids:
        return {}
    rows = (
        db.session.query(FBMShipmentTrackingEvent)
        .filter(FBMShipmentTrackingEvent.shipment_id.in_(sorted(shipment_ids)))
        .order_by(
            FBMShipmentTrackingEvent.shipment_id.asc(),
            FBMShipmentTrackingEvent.event_time.asc().nulls_last(),
            FBMShipmentTrackingEvent.observed_at.asc(),
            FBMShipmentTrackingEvent.id.asc(),
        )
        .all()
    )
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(int(row.shipment_id), []).append({
            "event_time": _iso(row.event_time),
            "observed_at": _iso(row.observed_at),
            "status": str(row.status or ""),
            "description": str(row.description or ""),
            "detail": str(row.detail or ""),
            "estimated_delivery_at": _iso(row.estimated_delivery_at),
            "package_count": row.package_count,
            "package_data": row.package_data,
        })
    return result


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
        # The canonical FBM page now projects promise truth before render. Keep
        # this signal as compatibility for other/legacy render paths, but never
        # perform a second DB read for rows that already carry that projection.
        missing_items = [
            item for item in items
            if isinstance(item, dict)
            and item.get("order") is not None
            and "delivery_promise" not in item
        ]
        keys = {
            (int(getattr(item.get("order"), "store_id", 0) or 0), str(getattr(item.get("order"), "marketplace_order_id", "") or "").strip())
            for item in missing_items
        }
        keys = {key for key in keys if key[0] > 0 and key[1]}
        profile_promises = _profile_promises(keys) if keys else {}
        operational_promises = _operational_promises(keys) if keys else {}
        shipment_ids = {
            int(getattr(item.get("shipment"), "id", 0) or 0)
            for item in items
            if isinstance(item, dict) and item.get("shipment") is not None
        }
        shipment_ids.discard(0)
        tracking_events_by_shipment = _tracking_events(shipment_ids)
        rendered_truth: dict[int, dict[str, Any]] = {}

        for item in items:
            if not isinstance(item, dict):
                continue
            order = item.get("order")
            key = (int(getattr(order, "store_id", 0) or 0), str(getattr(order, "marketplace_order_id", "") or "").strip())
            if "delivery_promise" in item:
                promise = item.get("delivery_promise")
            else:
                promise = _merge_promise(profile_promises.get(key), operational_promises.get(key))
            # Keep raw persisted UTC promise truth for comparisons/audit, while
            # the template receives a Europe/London presentation copy.
            item["delivery_promise"] = _display_promise(promise)
            shipment = item.get("shipment")
            performance = _delivery_performance(shipment, promise)
            item["delivery_performance"] = performance
            tracking_authority = _shipment_tracking_authority(shipment, order)
            shipment_id = int(getattr(shipment, "id", 0) or 0) if shipment is not None else 0
            shipment_events = tracking_events_by_shipment.get(shipment_id, [])
            first_scan_at = ""
            if shipment is not None and getattr(shipment, "label_purchased_at", None) is not None:
                for event in shipment_events:
                    if _is_pre_scan_event(event):
                        continue
                    candidate = str(event.get("event_time") or event.get("observed_at") or "").strip()
                    if candidate:
                        first_scan_at = candidate
                        break
            canonical_pickup_at = _iso(getattr(shipment, "carrier_accepted_at", None)) if shipment is not None else ""
            pickup_at = canonical_pickup_at or first_scan_at
            order_id = int(getattr(order, "id", 0) or 0)
            if order_id:
                rendered_truth[order_id] = {
                    "shipment_state": str(item.get("shipment_state") or ""),
                    "order_created_at": _iso(getattr(order, "created_at", None)),
                    "marketplace_created_at": _iso(getattr(order, "marketplace_created_at", None)),
                    "shipped_at": _iso(getattr(order, "shipped_at", None)),
                    "label_purchased_at": _iso(getattr(shipment, "label_purchased_at", None)) if shipment is not None else "",
                    "marketplace_confirmed_at": _iso(getattr(shipment, "marketplace_confirmed_at", None)) if shipment is not None else "",
                    "carrier_accepted_at": pickup_at,
                    "first_movement_at": _iso(getattr(shipment, "first_movement_at", None)) if shipment is not None else "",
                    "delivered_at": _iso(getattr(shipment, "delivered_at", None)) if shipment is not None else "",
                    "last_provider_checked_at": _iso(getattr(shipment, "last_provider_checked_at", None)) if shipment is not None else "",
                    "last_provider_status": str(getattr(shipment, "last_provider_status", "") or "") if shipment is not None else "",
                    "ship_by_at": _iso((promise or {}).get("ship_by_at")),
                    "earliest_delivery_at": _iso((promise or {}).get("earliest_delivery_at")),
                    "latest_delivery_at": _iso((promise or {}).get("latest_delivery_at")),
                    "delivery_performance": performance,
                    "shipping_source": _shipping_source(shipment),
                    "carrier": tracking_authority["carrier"],
                    "service": tracking_authority["service"],
                    "tracking_number": tracking_authority["tracking_number"],
                    "provider_shipment_id": str(getattr(shipment, "provider_shipment_id", "") or "") if shipment is not None else "",
                    "marketplace_order_id": str(getattr(order, "marketplace_order_id", "") or ""),
                    "tracking_events": shipment_events,
                }

            provider = str(getattr(shipment, "provider", "") or "").strip().lower()
            service = str((promise or {}).get("shipping_service") or "").strip()
            platform = str(item.get("platform") or getattr(getattr(order, "store", None), "platform", "") or "").strip().lower()
            if shipment is not None and provider == "marketplace" and platform == "amazon" and service:
                shipment.service = service

        g.fbm_delivery_truth_by_order_id = rendered_truth

    app._bt38_fbm_db_delivery_promise_alignment = True
