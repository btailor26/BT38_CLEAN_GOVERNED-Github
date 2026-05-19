"""BT38 Governed Amazon Live PATCH Layer."""

from __future__ import annotations

import json


def governed_amazon_quantity_patch(*, store, listing, sku: str, quantity: int, marketplace_id: str, command_id: str, approval_id: str):
    return {
        "success": False,
        "ok": False,
        "governed": True,
        "execution_blocked": True,
        "reason": "PLACEHOLDER - awaiting live SP-API PATCH implementation",
        "sku": sku,
        "quantity": quantity,
        "command_id": command_id,
        "approval_id": approval_id,
        "store_id": getattr(store, "id", None),
        "listing_id": getattr(listing, "id", None),
    }
