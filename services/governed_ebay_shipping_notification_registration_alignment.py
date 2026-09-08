"""Wire the existing eBay shipment notification capability into registration.

This is alignment only.  ORDER_CONFIRMATION remains the canonical order-intake
subscription.  When the existing registration path has a valid destination, it
also asks the already-implemented ITEM_MARKED_SHIPPED alignment to ensure that
subscription for the same destination/store.

No worker, poller, importer, order replay or marketplace order write is added.
A legacy seller grant without commerce.shipping remains usable and is marked for
one-time reauthorization by the existing shipping alignment.
"""
from __future__ import annotations

from typing import Any

import services.governed_ebay_notification_registration as _registration
# Normalize eBay's existing ITEM_MARKED_SHIPPED payload shape before the
# canonical governed webhook executor handles it.
import services.governed_ebay_item_marked_shipped_alignment  # noqa: F401


_ORIGINAL = _registration.ensure_ebay_order_notification_registration
_INSTALLED = False


def _aligned_registration(*, store: Any, access_token: str) -> dict[str, Any]:
    result = _ORIGINAL(store=store, access_token=access_token)
    if not isinstance(result, dict) or not result.get("success"):
        return result

    destination_id = result.get("destination_id")
    if not destination_id:
        return result

    # Import lazily to avoid the intentional helper dependency from the shipping
    # alignment back to this registration module during module initialization.
    from services.governed_ebay_shipping_notification_alignment import (
        ensure_ebay_shipping_notification_alignment,
    )

    try:
        shipping = ensure_ebay_shipping_notification_alignment(
            store=store,
            access_token=access_token,
            destination_id=str(destination_id),
        )
    except Exception as exc:
        # Shipment notification is an accelerator/capability.  Never break the
        # already-proven ORDER_CONFIRMATION registration because this optional
        # scope is absent or eBay temporarily rejects its registration call.
        shipping = {
            "success": False,
            "ok": False,
            "enabled": False,
            "topic_id": "ITEM_MARKED_SHIPPED",
            "reason": "shipping_notification_alignment_failed",
            "error": str(exc)[:1000],
            "marketplace_write_started": False,
        }

    result["shipping_notification"] = shipping
    result["shipping_notification_enabled"] = bool(shipping.get("enabled"))
    result["shipping_notification_reauthorization_required"] = bool(
        shipping.get("reauthorization_required")
        or shipping.get("authorization_required")
    )
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _registration.ensure_ebay_order_notification_registration = _aligned_registration
    _INSTALLED = True


install()
