"""Wire the existing eBay shipment notification capability into registration.

This is alignment only. ORDER_CONFIRMATION remains the canonical order-intake
subscription. When the existing registration path has a valid destination, it
also asks the already-implemented ITEM_MARKED_SHIPPED alignment to ensure that
subscription for the same destination/store.

The same existing post-deploy eBay reconciler is also invoked once when the
single governed runtime engine starts. This is restart/deployment recovery only:
no worker, poller, scheduler, importer duplication or marketplace order write is
introduced by this module.
"""
from __future__ import annotations

from typing import Any

import services.governed_ebay_notification_registration as _registration
# Normalize eBay's existing ITEM_MARKED_SHIPPED payload shape before the
# canonical governed webhook executor handles it.
import services.governed_ebay_item_marked_shipped_alignment  # noqa: F401


_ORIGINAL = _registration.ensure_ebay_order_notification_registration
_INSTALLED = False
_RUNTIME_INSTALLED = False


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
        # Shipment notification is an accelerator/capability. Never break the
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


def _install_runtime_startup_alignment() -> None:
    """Run the existing bounded eBay post-deploy alignment once per engine start."""
    global _RUNTIME_INSTALLED
    if _RUNTIME_INSTALLED:
        return

    import services.governed_runtime_engine as runtime

    original_engine_loop = runtime._engine_loop

    def _engine_loop_with_ebay_post_deploy_alignment(app):
        try:
            with app.app_context():
                from services.governed_ebay_post_deploy_alignment import (
                    align_ebay_notifications_and_recover_missed_changes,
                )

                result = align_ebay_notifications_and_recover_missed_changes(
                    store_id=23,
                    max_days=7,
                )
                runtime._safe_log(
                    "eBay post-deploy alignment complete "
                    f"success={bool(result.get('success'))} "
                    f"shipping_enabled={bool((result.get('shipping_notification') or {}).get('enabled'))}"
                )
        except Exception as exc:
            runtime._safe_error("eBay post-deploy alignment failed", exc)

        return original_engine_loop(app)

    runtime._engine_loop = _engine_loop_with_ebay_post_deploy_alignment
    _RUNTIME_INSTALLED = True


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _registration.ensure_ebay_order_notification_registration = _aligned_registration
    _install_runtime_startup_alignment()
    _INSTALLED = True


install()
