"""Event-driven Packlink shipment callback processing for BT38 FBM.

No polling loop lives here. Packlink wakes BT38 with a shipment event; BT38 then
hydrates that exact Packlink shipment and feeds any paid label/tracking through
the existing post-purchase mapping and marketplace-confirmation path.

Packlink's shipment custom reference is the marketplace order reference. That
allows a paid Packlink shipment to flow back into BT38 even when BT38 did not
create a Packlink draft first.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from extensions import db
from fbm_models import FBMShipment
from fbm_tracking_event_models import FBMShipmentTrackingEvent
from models import MarketplaceOrder
from services.fbm_packlink_adapter import PacklinkAdapter, PacklinkRequestError
from services.fbm_post_purchase import persist_external_label, reconcile_provider_lifecycle_state


SUPPORTED_EVENTS = {
    "shipment.carrier.success",
    "shipment.carrier.fail",
    "shipment.label.ready",
    "shipment.label.fail",
    "shipment.tracking.update",
    "shipment.delivered",
}


class PacklinkCallbackError(RuntimeError):
    pass


def _platform(order: MarketplaceOrder) -> str:
    store = getattr(order, "store", None)
    return str(getattr(store, "platform", "") or "").strip() or "Unknown"


def _tracking_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in (
        "tracking_number",
        "trackingNumber",
        "tracking_code",
        "trackingCode",
        "tracking",
        "parcel_tracking_number",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _tracking_code(value)
            if nested:
                return nested

    for key in ("tracking_codes", "trackings"):
        values = payload.get(key)
        if isinstance(values, str) and values.strip():
            return values.strip()
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    candidate = (
                        value.get("code")
                        or value.get("tracking_number")
                        or value.get("tracking")
                    )
                    if candidate:
                        return str(candidate).strip() or None

    for key in ("carrier", "shipment", "package", "tracking_info"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            value = _tracking_code(nested)
            if value:
                return value
    return None


def _latest_tracking(history: list[dict[str, Any]]) -> str | None:
    for item in reversed(history or []):
        value = _tracking_code(item)
        if value:
            return value
    return None


def extract_packlink_tracking(
    provider_payload: Any,
    tracking_history: list[dict[str, Any]] | None = None,
    fallback: Any = None,
) -> str | None:
    """Resolve one Packlink tracking number consistently for every BT38 path."""
    direct = _tracking_code(provider_payload)
    if direct:
        return direct
    history_value = _latest_tracking(tracking_history or [])
    if history_value:
        return history_value
    fallback_text = str(fallback or "").strip()
    return fallback_text or None


def _status_texts(payload: Any) -> list[str]:
    """Collect provider lifecycle text without guessing from tracking presence."""
    values: list[str] = []
    if isinstance(payload, str):
        text = payload.strip()
        return [text] if text else []
    if isinstance(payload, list):
        for item in payload:
            values.extend(_status_texts(item))
        return values
    if not isinstance(payload, dict):
        return values

    for key in (
        "status",
        "state",
        "event",
        "event_name",
        "eventName",
        "status_name",
        "statusName",
        "description",
        "message",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, (dict, list)):
            values.extend(_status_texts(value))

    for key in ("events", "history", "tracking_history", "trackingHistory", "tracking_info"):
        nested = payload.get(key)
        if isinstance(nested, (dict, list)):
            values.extend(_status_texts(nested))
    return values


def _provider_state_lifecycle(provider_state: Any) -> str | None:
    """Return only the lifecycle explicitly stated by Packlink's current state."""
    normalized = (
        str(provider_state or "")
        .strip()
        .upper()
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
        .replace("/", "_")
    )
    if not normalized:
        return None
    if normalized in {
        "DELIVERED",
        "DELIVERY_COMPLETE",
        "DELIVERY_COMPLETED",
        "SUCCESSFULLY_DELIVERED",
        "COMPLETED_DELIVERY",
    } or normalized.endswith("_DELIVERED"):
        return "DELIVERED"
    if normalized in {"IN_TRANSIT", "OUT_FOR_DELIVERY", "IN_DELIVERY", "ON_ROUTE"}:
        return "IN_TRANSIT"
    if normalized in {
        "ACCEPTED",
        "CARRIER_ACCEPTED",
        "COLLECTED",
        "PICKED_UP",
        "PICKEDUP",
        "RECEIVED_BY_CARRIER",
    }:
        return "ACCEPTED"
    return None


def _canonical_tracking_lifecycle(
    provider_state: Any,
    tracking_history: list[dict[str, Any]] | None,
) -> str | None:
    """Return strongest lifecycle only from explicit provider state fields."""
    states: list[str] = []
    if provider_state:
        states.append(str(provider_state))
    for item in tracking_history or []:
        if not isinstance(item, dict):
            continue
        value = item.get("status_code") or item.get("status") or item.get("state") or item.get("event") or item.get("event_name")
        if value:
            states.append(str(value))
    lifecycles = [_provider_state_lifecycle(value) for value in states]
    if "DELIVERED" in lifecycles:
        return "DELIVERED"
    if "IN_TRANSIT" in lifecycles:
        return "IN_TRANSIT"
    if "ACCEPTED" in lifecycles:
        return "ACCEPTED"
    return None



def _parse_tracking_event_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    text_value = str(value or "").strip()
    if not text_value:
        return None
    normalized = text_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _tracking_event_time(item: dict[str, Any]) -> datetime | None:
    for key in ("event_time", "eventTime", "date", "datetime", "timestamp", "created_at", "createdAt"):
        parsed = _parse_tracking_event_time(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _persist_packlink_tracking_history(
    shipment: FBMShipment,
    tracking_history: list[dict[str, Any]] | None,
    *,
    observed_at: datetime,
) -> list[FBMShipmentTrackingEvent]:
    """Persist exact Packlink carrier history already fetched for this event.

    This function never calls Packlink. Provider observation time and carrier
    event time remain separate facts.
    """
    if shipment.id is None:
        db.session.flush()

    persisted: list[FBMShipmentTrackingEvent] = []
    for index, item in enumerate(tracking_history or []):
        if not isinstance(item, dict):
            continue
        event_time = _tracking_event_time(item)
        status = str(item.get("status_code") or item.get("status") or item.get("state") or item.get("event") or "").strip() or None
        description = str(item.get("description") or item.get("message") or item.get("status_name") or "").strip() or None
        detail = str(item.get("detail") or item.get("details") or item.get("status_description") or "").strip() or None
        event_key = str(
            item.get("id")
            or item.get("event_id")
            or item.get("eventId")
            or "|".join([
                event_time.isoformat() if event_time else "",
                status or "",
                description or "",
                detail or "",
            ])
        )[:180]
        existing = FBMShipmentTrackingEvent.query.filter_by(
            shipment_id=int(shipment.id),
            event_key=event_key,
        ).first()
        if existing is None:
            existing = FBMShipmentTrackingEvent(
                shipment_id=int(shipment.id),
                provider="packlink",
                event_key=event_key,
            )
            db.session.add(existing)
        existing.event_time = event_time
        existing.status = status
        existing.description = description
        existing.detail = detail
        existing.raw_event = item
        existing.observed_at = observed_at
        persisted.append(existing)
    return persisted


def _milestone_event_time(events: list[FBMShipmentTrackingEvent], milestone: str) -> datetime | None:
    matches: list[datetime] = []
    for event in events:
        lifecycle = _canonical_tracking_lifecycle(
            None,
            [{
                "status": event.status,
                "description": event.description,
                "detail": event.detail,
            }],
        )
        if lifecycle == milestone and event.event_time is not None:
            matches.append(event.event_time)
    if not matches:
        return None
    return max(matches) if milestone == "DELIVERED" else min(matches)


def reconcile_packlink_tracking_lifecycle(
    shipment: FBMShipment,
    *,
    provider_state: Any = None,
    tracking_history: list[dict[str, Any]] | None = None,
    observed_at: datetime | None = None,
) -> str:
    """Project exact Packlink shipment/history truth onto BT38 Journey milestones."""
    current = _provider_state_lifecycle(provider_state)
    canonical = current or _canonical_tracking_lifecycle(None, tracking_history)
    checked_at = observed_at or datetime.utcnow()
    persisted_events = _persist_packlink_tracking_history(
        shipment,
        tracking_history,
        observed_at=checked_at,
    )
    accepted_at = _milestone_event_time(persisted_events, "ACCEPTED")
    movement_at = _milestone_event_time(persisted_events, "IN_TRANSIT")
    delivered_at = _milestone_event_time(persisted_events, "DELIVERED")

    # Carrier event timestamps are marketplace/provider truth. checked_at is
    # only when BT38 observed that truth and must never become the carrier time.
    if accepted_at is not None:
        shipment.carrier_accepted_at = accepted_at
    if movement_at is not None:
        shipment.first_movement_at = movement_at
    if delivered_at is not None:
        shipment.delivered_at = delivered_at

    # Packlink's current shipment state is newer authority than older history or
    # stale BT38 terminal fields. This only removes milestones that the current
    # provider state explicitly disproves; tracking/label presence never promotes
    # a physical carrier milestone by itself.
    if current == "IN_TRANSIT":
        shipment.delivered_at = None
        shipment.status = "in_transit"
    elif current == "ACCEPTED":
        shipment.delivered_at = None
        shipment.first_movement_at = None
        shipment.status = "accepted"

    if canonical:
        shipment.last_provider_status = canonical
    elif str(provider_state or "").strip():
        shipment.last_provider_status = str(provider_state).strip()
    shipment.last_provider_checked_at = checked_at
    return reconcile_provider_lifecycle_state(
        shipment,
        observed_at=shipment.last_provider_checked_at,
    )


def _first_label_url(labels: list[Any]) -> str | None:
    for label in labels or []:
        if isinstance(label, str) and label.strip():
            return label.strip()
        if isinstance(label, dict):
            for key in ("url", "label_url", "download_url"):
                value = label.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _provider_identity(
    provider_payload: dict[str, Any],
    shipment: FBMShipment,
) -> tuple[str | None, str | None, str | None]:
    carrier_raw = provider_payload.get("carrier")
    if isinstance(carrier_raw, dict):
        carrier = (
            str(carrier_raw.get("name") or carrier_raw.get("label") or "").strip()
            or shipment.carrier
        )
    else:
        carrier = str(carrier_raw or shipment.carrier or "").strip() or None

    service_raw = provider_payload.get("service")
    if isinstance(service_raw, dict):
        service = (
            str(service_raw.get("name") or service_raw.get("label") or "").strip()
            or shipment.service
        )
        service_id = str(
            service_raw.get("id")
            or provider_payload.get("service_id")
            or shipment.provider_service_id
            or ""
        ).strip() or None
    else:
        service = str(
            service_raw or provider_payload.get("service_name") or shipment.service or ""
        ).strip() or None
        service_id = str(
            provider_payload.get("service_id") or shipment.provider_service_id or ""
        ).strip() or None
    return carrier, service, service_id


def _apply_lifecycle_state(shipment: FBMShipment, event_name: str, now: datetime) -> None:
    # Packlink's carrier.success means the booked carrier/service was accepted by
    # Packlink. It does not prove physical collection. Pickup can only be promoted
    # by explicit carrier tracking history through reconcile_packlink_tracking_lifecycle.
    if event_name == "shipment.carrier.success":
        if shipment.delivered_at is None and shipment.first_movement_at is None:
            shipment.status = "awaiting_carrier_acceptance"
    elif event_name == "shipment.tracking.update":
        # The tracking-update callback itself is only a wake-up signal. The
        # provider history read above owns whether the parcel was accepted/moving.
        if shipment.delivered_at is None and shipment.first_movement_at is None:
            shipment.status = "awaiting_carrier_acceptance"
    elif event_name == "shipment.delivered":
        # The callback is a wake-up/status signal. Exact carrier milestone times
        # come only from persisted tracking-history event_time values.
        shipment.status = "delivered"


def _attach_by_marketplace_reference(
    *,
    reference: str,
    custom_reference: str | None,
) -> tuple[FBMShipment | None, MarketplaceOrder | None, str | None]:
    """Attach an externally-created Packlink shipment using marketplace Reference.

    Tracking is the completion boundary. Before tracking exists, a newer Packlink
    shipment for the same order may replace the stale/deleted draft reference.
    After tracking exists, a different Packlink shipment using the same order
    number is held until the user classifies it as a return or replacement.
    """
    if not custom_reference:
        return None, None, "marketplace_reference_missing"

    orders = (
        MarketplaceOrder.query
        .filter_by(marketplace_order_id=custom_reference)
        .order_by(MarketplaceOrder.id.asc())
        .all()
    )
    if not orders:
        return None, None, "marketplace_order_not_found"
    if len(orders) != 1:
        return None, None, "marketplace_reference_ambiguous"

    order = orders[0]
    shipment = (
        FBMShipment.query
        .filter_by(
            store_id=order.store_id,
            marketplace_order_id=order.marketplace_order_id,
            provider="packlink",
        )
        .order_by(FBMShipment.id.desc())
        .first()
    )
    if shipment is None:
        shipment = FBMShipment(
            store_id=order.store_id,
            marketplace_order_id=order.marketplace_order_id,
            provider="packlink",
            provider_shipment_id=reference,
            purchase_key=f"packlink_external:{order.store_id}:{order.marketplace_order_id}",
            purchase_status="provider_event_received",
            status="awaiting_label",
        )
        db.session.add(shipment)
    else:
        existing_reference = str(shipment.provider_shipment_id or "").strip()
        completed_tracking = str(shipment.tracking_number or "").strip()
        if completed_tracking and existing_reference and existing_reference != reference:
            return (
                None,
                order,
                "additional_shipment_requires_return_or_replacement_confirmation",
            )
        shipment.provider_shipment_id = reference
        if shipment.purchase_status not in {"purchased"}:
            shipment.purchase_status = "provider_event_received"
    db.session.commit()
    return shipment, order, None


def process_packlink_callback(
    payload: dict[str, Any],
    *,
    adapter: PacklinkAdapter | None = None,
) -> dict[str, Any]:
    """Process one Packlink callback safely and idempotently."""
    if not isinstance(payload, dict):
        raise PacklinkCallbackError("Packlink callback payload must be a JSON object.")

    event_name = str(payload.get("event") or payload.get("name") or "").strip()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    reference = str(
        data.get("shipment_reference")
        or data.get("shipmentReference")
        or payload.get("shipment_reference")
        or ""
    ).strip()
    custom_reference = str(
        data.get("shipment_custom_reference")
        or data.get("shipmentCustomReference")
        or payload.get("shipment_custom_reference")
        or payload.get("shipmentCustomReference")
        or data.get("reference")
        or payload.get("reference")
        or ""
    ).strip() or None

    if not event_name:
        raise PacklinkCallbackError("Packlink callback event name is missing.")
    if event_name not in SUPPORTED_EVENTS:
        return {
            "success": True,
            "ignored": True,
            "event": event_name,
            "reason": "unsupported_event",
        }
    if not reference:
        raise PacklinkCallbackError("Packlink callback shipment reference is missing.")

    shipment = (
        FBMShipment.query
        .filter_by(provider="packlink", provider_shipment_id=reference)
        .order_by(FBMShipment.id.desc())
        .first()
    )
    order = None
    if shipment is None:
        shipment, order, attach_error = _attach_by_marketplace_reference(
            reference=reference,
            custom_reference=custom_reference,
        )
        if shipment is None:
            return {
                "success": True,
                "ignored": True,
                "event": event_name,
                "provider_reference": reference,
                "custom_reference": custom_reference,
                "reason": attach_error or "shipment_not_known_to_bt38",
            }

    now = datetime.utcnow()
    shipment.last_provider_checked_at = now
    shipment.last_provider_status = event_name

    if event_name in {"shipment.carrier.fail", "shipment.label.fail"}:
        shipment.status = "provider_error"
        shipment.purchase_error = str(data.get("message") or data.get("error") or event_name)
        db.session.commit()
        return {
            "success": True,
            "event": event_name,
            "shipment_id": shipment.id,
            "provider_reference": reference,
            "state": "provider_error",
        }

    adapter = adapter or PacklinkAdapter()
    provider_payload = adapter.get_shipment(reference)
    labels = adapter.get_labels(reference)
    tracking_history = adapter.get_tracking_status(reference=reference)

    provider_state = str(
        provider_payload.get("state") or provider_payload.get("status") or event_name
    ).strip()
    reconcile_packlink_tracking_lifecycle(
        shipment,
        provider_state=provider_state,
        tracking_history=tracking_history,
        observed_at=now,
    )
    carrier, service, service_id = _provider_identity(provider_payload, shipment)
    tracking = extract_packlink_tracking(
        provider_payload,
        tracking_history,
        shipment.tracking_number,
    )

    if carrier:
        shipment.carrier = carrier
    if service:
        shipment.service = service
    if service_id:
        shipment.provider_service_id = service_id
    if tracking:
        shipment.tracking_number = tracking

    label_url = _first_label_url(labels)
    if event_name == "shipment.label.ready" and not label_url:
        raise PacklinkRequestError(
            "Packlink reported label ready but the label URL is not readable yet.",
            status_code=503,
        )

    result: dict[str, Any] | None = None
    if label_url:
        if order is None:
            order = MarketplaceOrder.query.filter_by(
                store_id=shipment.store_id,
                marketplace_order_id=shipment.marketplace_order_id,
            ).order_by(MarketplaceOrder.id.asc()).first()
        if order is None:
            shipment.status = "order_missing"
            db.session.commit()
            return {
                "success": False,
                "held": True,
                "event": event_name,
                "shipment_id": shipment.id,
                "reason": "marketplace_order_missing",
            }

        result = persist_external_label(
            shipment=shipment,
            marketplace=_platform(order),
            provider="packlink",
            provider_shipment_id=reference,
            carrier=carrier,
            service=service,
            tracking_number=tracking,
            provider_service_id=service_id,
            label={
                "type": "LABEL",
                "format": "PDF",
                "url": label_url,
                "storage_ref": reference,
            },
        )

    _apply_lifecycle_state(shipment, event_name, now)
    reconcile_packlink_tracking_lifecycle(
        shipment,
        provider_state=provider_state,
        tracking_history=tracking_history,
        observed_at=now,
    )
    db.session.commit()

    response = {
        "success": True,
        "event": event_name,
        "shipment_id": shipment.id,
        "provider_reference": reference,
        "custom_reference": custom_reference,
        "label_ready": bool(label_url),
        "tracking_number": tracking,
        "provider_status": shipment.last_provider_status,
        "shipment_status": shipment.status,
    }
    if result:
        response.update(result)
        response["shipment_status"] = shipment.status
    return response


def recover_packlink_shipments_for_day(
    target_day: date,
    *,
    adapter: PacklinkAdapter | None = None,
) -> dict[str, Any]:
    """One-shot recovery for exact Packlink shipments already known to BT38.

    A recovery run for today audits every Packlink shipment already known to
    BT38, regardless of age or apparent completeness. This deliberately repairs
    legacy records that can look complete while containing inferred timestamps.
    A non-today target keeps date-scoped recovery for explicit historical work.
    Recovery is lifecycle-only: it never confirms a marketplace shipment and
    never purchases or changes postage.
    """
    start = datetime.combine(target_day, time.min)
    end = start + timedelta(days=1)
    query = FBMShipment.query.filter(
        FBMShipment.provider == "packlink",
        FBMShipment.provider_shipment_id.isnot(None),
    )
    recover_all = target_day == datetime.utcnow().date()
    if recover_all:
        shipments = query.order_by(FBMShipment.id.asc()).all()
    else:
        shipments = (
            query
            .filter(FBMShipment.created_at >= start, FBMShipment.created_at < end)
            .order_by(FBMShipment.id.asc())
            .all()
        )

    adapter = adapter or PacklinkAdapter()
    results: list[dict[str, Any]] = []
    for shipment in shipments:
        try:
            lifecycle_only = bool(recover_all or shipment.marketplace_confirmed_at is not None)
            if lifecycle_only:
                now = datetime.utcnow()
                provider_payload = adapter.get_shipment(shipment.provider_shipment_id)
                tracking_history = adapter.get_tracking_status(reference=shipment.provider_shipment_id)
                provider_state = str(
                    provider_payload.get("state") or provider_payload.get("status") or shipment.last_provider_status or ""
                ).strip()
                tracking = extract_packlink_tracking(
                    provider_payload,
                    tracking_history,
                    shipment.tracking_number,
                )
                if tracking:
                    shipment.tracking_number = tracking
                reconcile_packlink_tracking_lifecycle(
                    shipment,
                    provider_state=provider_state,
                    tracking_history=tracking_history,
                    observed_at=now,
                )
                db.session.commit()
                results.append({
                    "success": True,
                    "shipment_id": shipment.id,
                    "marketplace_order_id": shipment.marketplace_order_id,
                    "provider_reference": shipment.provider_shipment_id,
                    "lifecycle_only": True,
                    "historical_recovery": recover_all,
                    "marketplace_write_attempted": False,
                    "provider_status": shipment.last_provider_status,
                    "shipment_status": shipment.status,
                    "tracking_number": shipment.tracking_number,
                })
                continue

            result = process_packlink_callback(
                {
                    "event": "shipment.label.ready",
                    "data": {
                        "shipment_reference": shipment.provider_shipment_id,
                        "shipment_custom_reference": shipment.marketplace_order_id,
                    },
                },
                adapter=adapter,
            )
            results.append({
                "shipment_id": shipment.id,
                "marketplace_order_id": shipment.marketplace_order_id,
                "provider_reference": shipment.provider_shipment_id,
                **result,
            })
        except PacklinkRequestError as exc:
            results.append({
                "success": False,
                "shipment_id": shipment.id,
                "marketplace_order_id": shipment.marketplace_order_id,
                "provider_reference": shipment.provider_shipment_id,
                "message": str(exc),
                "status_code": exc.status_code,
            })
        except Exception as exc:
            results.append({
                "success": False,
                "shipment_id": shipment.id,
                "marketplace_order_id": shipment.marketplace_order_id,
                "provider_reference": shipment.provider_shipment_id,
                "message": str(exc),
            })

    return {
        "success": True,
        "target_day": target_day.isoformat(),
        "checked": len(shipments),
        "results": results,
    }
