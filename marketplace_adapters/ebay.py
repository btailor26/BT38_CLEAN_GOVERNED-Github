"""BT38 governed eBay live adapter."""

from __future__ import annotations

import json
import requests
from typing import Any, Mapping

from marketplace_adapters.base import GovernedMarketplaceAdapter


class EbayAdapter(GovernedMarketplaceAdapter):
    marketplace = "ebay"
    adapter_name = "ebay"

    def execute(self, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        store = payload.get("_governed_store") or payload.get("store")
        listing = payload.get("_governed_listing") or payload.get("listing")

        if not store:
            return self.blocked_result(
                action=action,
                payload=payload,
                reason="Missing store for eBay execution.",
            )

        raw = getattr(store, "api_key", None)

        creds = None

        if isinstance(raw, str):
            try:
                creds = json.loads(raw)
            except Exception:
                creds = None
        elif isinstance(raw, dict):
            creds = raw

        if not creds:
            return self.blocked_result(
                action=action,
                payload=payload,
                reason="Missing eBay credentials.",
            )

        token = (
            creds.get("access_token")
            or creds.get("oauth_token")
            or creds.get("token")
        )

        if not token:
            return self.blocked_result(
                action=action,
                payload=payload,
                reason="Missing eBay access token.",
            )

        item_id = (
            payload.get("external_listing_id")
            or getattr(listing, "external_listing_id", None)
        )

        if not item_id:
            return self.blocked_result(
                action=action,
                payload=payload,
                reason="Missing eBay item id.",
            )

        quantity = payload.get("quantity")

        if quantity is None and listing:
            stock = getattr(listing, "warehouse_stock", None)
            if stock:
                quantity = getattr(stock, "quantity", 0)

        body = {
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": int(quantity or 0)
                }
            }
        }

        url = f"https://api.ebay.com/sell/inventory/v1/inventory_item/{item_id}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Language": "en-GB",
        }

        response = requests.put(
            url,
            headers=headers,
            json=body,
            timeout=30,
        )

        ok = response.status_code < 300

        return {
            "ok": ok,
            "success": ok,
            "marketplace": "ebay",
            "action": action,
            "status_code": response.status_code,
            "response_text": response.text[:4000],
            "live_write": True,
            "external_listing_id": item_id,
            "quantity": quantity,
        }
