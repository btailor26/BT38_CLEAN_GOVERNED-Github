"""Exact event-driven Packlink processing for BT38 FBM.

No polling or batch scanning lives here. A Packlink callback wakes BT38 for one
shipment reference only. Label-ready may hydrate the exact provider shipment to
obtain the purchased label. Tracking movement is consumed from the callback
payload itself and never performs a second Packlink tracking read.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from extensions import db
from fbm_models import FBMShipment
from fbm_tracking_event_models import FBMShipmentTrackingEvent
from models import MarketplaceOrder
from services.fbm_packlink_adapter import PacklinkAdapter, PacklinkRequestError
from services.fbm_packlink_callback import (
    PacklinkCallbackError,
    SUPPORTED_EVENTS,
    _apply_lifecycle_state,
    _attach_by_marketplace_reference,
    _first_label_url,
    _platform,
    _provider_identity,
    extract_packlink_tracking,
    reconcile_packlink_tracking_lifecycle,
)
from services.fbm_post_purchase import persist_external_label


def _event_parts(payload: dict[str, Any]) -> tuple[str, dict[str, Any], str, str | None]:
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
    return event_name, data, reference, custom_reference


def _find_exact_shipment(reference: str, custom_reference: str | None):
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
        return shipment, order, attach_error
    return shipment, order, None


def _callback_tracking_history(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only tracking events already supplied inside this callback."""
    for key in ("tracking_history", "trackingHistory", "history", "events"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
    tracking_info = data.get("tracking_info")
    if isinstance(tracking_info, list):
        return [item for item in tracking_info if isinstance(item, dict)]
    if isinstance(tracking_info, dict):
        return [tracking_info]
    return [data] if data else []


def _callback_provider_state(data: dict[str, Any], event_name: str) -> str:
    """Resolve lifecycle text directly from Packlink's webhook payload."""
    for key in (
        "state",
        "status",
        "status_name",
        "statusName",
        "event_status",
        "eventStatus",
        "description",
        "message",
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return event_name


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_provider_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if not isinstance(value, str) or not value.strip():
        return None
    text_value = value.strip()
    normalized = text_value[:-1] + "+00:00" if text_value.endswith("Z") else text_value
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
    except ValueError:
        return None


def _event_datetime(item: dict[str, Any]) -> datetime | None:
    for key in (
        "timestamp",
        "event_time",
        "eventTime",
        "event_date",
        "eventDate",
        "datetime",
        "date_time",
        "dateTime",
        "created_at",
        "createdAt",
        "updated_at",
        "updatedAt",
        "date",
    ):
        parsed = _parse_provider_datetime(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _estimated_delivery(data: dict[str, Any], item: dict[str, Any]) -> datetime | None:
    for source in (item, data):
        for key in (
            "estimated_delivery",
            "estimatedDelivery",
            "estimated_delivery_at",
            "estimatedDeliveryAt",
            "delivery_estimate",
            "deliveryEstimate",
            "eta",
        ):
            parsed = _parse_provider_datetime(source.get(key))
            if parsed is not None:
                return parsed
    return None


def _package_metadata(data: dict[str, Any]) -> tuple[int | None, Any]:
    for key in ("packages", "parcels"):
        value = data.get(key)
        if isinstance(value, list):
            return len(value), value
    for key in ("package", "parcel"):
        value = data.get(key)
        if isinstance(value, dict):
            return 1, value
    count = data.get("package_count") or data.get("packageCount") or data.get("parcel_count") or data.get("parcelCount")
    try:
        parsed_count = int(count) if count is not None else None
    except (TypeError, ValueError):
        parsed_count = None
    return parsed_count, None


def _tracking_event_key(shipment_id: int, item: dict[str, Any]) -> str:
    canonical = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:48]
    return f"{shipment_id}:{digest}"


def _persist_tracking_events(
    shipment: FBMShipment,
    *,
    data: dict[str, Any],
    history: list[dict[str, Any]],
    observed_at: datetime,
) -> int:
    """Persist webhook-supplied tracking history only; replay-safe and provider-read free."""
    package_count, package_data = _package_metadata(data)
    inserted = 0
    for item in history:
        event_key = _tracking_event_key(int(shipment.id), item)
        exists = (
            FBMShipmentTrackingEvent.query
            .filter_by(shipment_id=shipment.id, event_key=event_key)
            .first()
        )
        if exists is not None:
            continue
        status = _first_text(item, (
            "status", "state", "status_name", "statusName", "event_status", "eventStatus", "code"
        ))
        description = _first_text(item, (
            "description", "message", "status_description", "statusDescription", "label"
        ))
        detail = _first_text(item, (
            "detail", "details", "reason", "location", "event_description", "eventDescription"
        ))
        db.session.add(FBMShipmentTrackingEvent(
            shipment_id=shipment.id,
            provider="packlink",
            event_key=event_key,
            event_time=_event_datetime(item),
            status=status,
            description=description,
            detail=detail,
            estimated_delivery_at=_estimated_delivery(data, item),
            package_count=package_count,
            package_data=package_data,
            raw_event=item,
            observed_at=observed_at,
        ))
        inserted += 1
    return inserted


def process_packlink_event(
    payload: dict[str, Any],
    *,
    adapter: PacklinkAdapter | None = None,
) -> dict[str, Any]:
    """Process exactly one Packlink event without polling unrelated shipments."""
    if not isinstance(payload, dict):
        raise PacklinkCallbackError("Packlink callback payload must be a JSON object.")

    event_name, data, reference, custom_reference = _event_parts(payload)
    if not event_name:
        raise PacklinkCallbackError("Packlink callback event name is missing.")
    if event_name not in SUPPORTED_EVENTS:
        return {"success": True, "ignored": True, "event": event_name, "reason": "unsupported_event"}
    if not reference:
        raise PacklinkCallbackError("Packlink callback shipment reference is missing.")

    shipment, order, attach_error = _find_exact_shipment(reference, custom_reference)
    if shipment is None:
        return {
            "success": True,
            "ignored": True,
            "event": event_name,
            "provider_reference": reference,
            "custom_reference": custom_reference,
            "reason": attach_error or "shipment_not_known_to_bt38",
        }

    if shipment.marketplace_confirmed_at is not None and event_name == "shipment.label.ready":
        return {
            "success": True,
            "ignored": True,
            "event": event_name,
            "shipment_id": shipment.id,
            "provider_reference": reference,
            "reason": "marketplace_already_confirmed",
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

    if event_name == "shipment.label.ready":
        adapter = adapter or PacklinkAdapter()
        provider_payload = adapter.get_shipment(reference)
        labels = adapter.get_labels(reference)
        tracking_history = adapter.get_tracking_status(reference=reference)
        label_url = _first_label_url(labels)
        if not label_url:
            raise PacklinkRequestError(
                "Packlink reported label ready but the label URL is not readable yet.",
                status_code=503,
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
            label={"type": "LABEL", "format": "PDF", "url": label_url, "storage_ref": reference},
        )
        return {
            "success": True,
            "event": event_name,
            "shipment_id": shipment.id,
            "provider_reference": reference,
            "custom_reference": custom_reference,
            "label_ready": True,
            "tracking_number": shipment.tracking_number,
            **result,
        }

    if event_name == "shipment.tracking.update":
        callback_history = _callback_tracking_history(data)
        provider_state = _callback_provider_state(data, event_name)
        tracking = extract_packlink_tracking(data, callback_history, shipment.tracking_number)
        carrier, service, service_id = _provider_identity(data, shipment)
        if carrier:
            shipment.carrier = carrier
        if service:
            shipment.service = service
        if service_id:
            shipment.provider_service_id = service_id
        if tracking:
            shipment.tracking_number = tracking
        persisted_events = _persist_tracking_events(
            shipment,
            data=data,
            history=callback_history,
            observed_at=now,
        )
        reconcile_packlink_tracking_lifecycle(
            shipment,
            provider_state=provider_state,
            tracking_history=callback_history,
            observed_at=now,
        )
        db.session.commit()
        return {
            "success": True,
            "event": event_name,
            "shipment_id": shipment.id,
            "provider_reference": reference,
            "tracking_number": shipment.tracking_number,
            "shipment_status": shipment.status,
            "provider_status": shipment.last_provider_status,
            "tracking_events_persisted": persisted_events,
            "webhook_only": True,
        }

    _apply_lifecycle_state(shipment, event_name, now)
    db.session.commit()
    return {
        "success": True,
        "event": event_name,
        "shipment_id": shipment.id,
        "provider_reference": reference,
        "shipment_status": shipment.status,
        "webhook_only": True,
    }
