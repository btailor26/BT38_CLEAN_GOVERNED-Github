"""Align eBay ITEM_MARKED_SHIPPED with the existing governed lifecycle path.

This is intentionally narrow. eBay's Notification API shipment topic uses the
ITEM_MARKED_SHIPPED topic plus shippedDate/trackingNumber/carrier fields. The
canonical webhook executor already owns MarketplaceOrder lifecycle persistence;
this module only normalizes that exact payload shape so it is treated as a
terminal shipped event.

No importer, worker, poller, replay, marketplace write, or new shipment model is
introduced here.
"""
from __future__ import annotations

from typing import Any

import services.governed_webhook_execution as _execution


_ORIGINAL_CLASSIFY = _execution._classify_business_event
_ORIGINAL_EXTRACT = _execution._extract_order_lifecycle_values
_INSTALLED = False


def _is_item_marked_shipped(payload: dict, event_type: str | None = None) -> bool:
    normalized = str(event_type or _execution._event_type(payload) or "").strip().upper()
    if normalized == "ITEM_MARKED_SHIPPED":
        return True
    topic = str(
        _execution._deep_get(payload, "topic")
        or _execution._deep_get(payload, "notificationType")
        or ""
    ).strip().upper()
    return topic == "ITEM_MARKED_SHIPPED"


def _classify_business_event(event_type: str, payload: dict) -> str:
    if _is_item_marked_shipped(payload, event_type):
        return "tracking"
    return _ORIGINAL_CLASSIFY(event_type, payload)


def _extract_order_lifecycle_values(
    payload: dict,
    *,
    business_event: str | None = None,
) -> dict[str, Any]:
    values = _ORIGINAL_EXTRACT(payload, business_event=business_event)
    if not _is_item_marked_shipped(payload):
        return values

    shipped_at = values.get("shipped_at") or values.get("changed_at")
    if shipped_at is None:
        for key in (
            "shippedDate",
            "shipped_date",
            "shippedAt",
            "shipDate",
            "shipmentDate",
        ):
            shipped_at = _execution._parse_marketplace_event_timestamp(
                _execution._deep_get(payload, key)
            )
            if shipped_at is not None:
                break

    # ITEM_MARKED_SHIPPED is itself authoritative lifecycle state. The existing
    # executor remains responsible for updating the exact persisted order rows.
    values.update(
        {
            "recognized": True,
            "status": "shipped",
            "shipped_at": shipped_at,
            "changed_at": shipped_at or values.get("changed_at"),
            "terminal": True,
        }
    )
    return values


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _execution._classify_business_event = _classify_business_event
    _execution._extract_order_lifecycle_values = _extract_order_lifecycle_values
    _INSTALLED = True


install()
