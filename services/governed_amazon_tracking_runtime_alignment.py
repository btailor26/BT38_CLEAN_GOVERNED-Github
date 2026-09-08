"""Align Amazon exact-order verification with the existing package tracking readback.

The governed runtime already verifies one exact MarketplaceOrder identity after an
Amazon order event. This installer keeps that same event path and, for Amazon only,
reuses hydrate_amazon_tracking_for_order() to read the exact Orders v2026 PACKAGES
truth for that order. It adds no worker, poller, scan, importer, shipment table,
marketplace write, or second runtime path.
"""
from __future__ import annotations

from typing import Any

import services.governed_runtime_engine as runtime


_INSTALLED = False
_ORIGINAL = runtime._verify_exact_order


def _text(value: Any) -> str:
    return str(value or "").strip()


def _aligned_verify_exact_order(event: dict[str, Any]) -> dict[str, Any]:
    result = _ORIGINAL(event)
    if not result.get("verified"):
        return result

    marketplace = _text(event.get("marketplace")).lower()
    if marketplace not in {"amazon", "amazon_fbm"}:
        return result

    store_id = event.get("store_id")
    order_id = _text(event.get("order_id"))
    if store_id is None or not order_id:
        return {
            **result,
            "aligned": False,
            "amazon_tracking_readback": {
                "success": False,
                "skipped": True,
                "reason": "amazon_exact_order_scope_missing",
                "marketplace_write_started": False,
            },
        }

    from extensions import db
    from models import Store
    from services.governed_amazon_tracking_readback import (
        hydrate_amazon_tracking_for_order,
    )

    store = db.session.get(Store, int(store_id))
    if store is None:
        return {
            **result,
            "aligned": False,
            "amazon_tracking_readback": {
                "success": False,
                "skipped": True,
                "reason": "amazon_store_not_found",
                "marketplace_write_started": False,
            },
        }

    tracking = hydrate_amazon_tracking_for_order(
        store=store,
        marketplace_order_id=order_id,
        source=(
            f"{_text(event.get('source')) or 'amazon_webhook'}:"
            "exact_order_tracking_readback"
        ),
    )
    return {
        **result,
        "aligned": bool(tracking.get("success")),
        "amazon_tracking_readback": tracking,
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    runtime._verify_exact_order = _aligned_verify_exact_order
    _INSTALLED = True


install()
