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

        sku = (
            payload.get("sku")
            or getattr(listing, "external_sku", None)
            or ""
        )

        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{token}</eBayAuthToken>
  </RequesterCredentials>
  <ErrorLanguage>en_GB</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <InventoryStatus>
    <ItemID>{item_id}</ItemID>
    <SKU>{sku}</SKU>
    <Quantity>{int(quantity or 0)}</Quantity>
  </InventoryStatus>
</ReviseInventoryStatusRequest>"""

        url = "https://api.ebay.com/ws/api.dll"

        headers = {
            "Content-Type": "text/xml",
            "X-EBAY-API-CALL-NAME": "ReviseInventoryStatus",
            "X-EBAY-API-SITEID": str(creds.get("site_id") or creds.get("siteid") or "3"),
            "X-EBAY-API-COMPATIBILITY-LEVEL": str(creds.get("compatibility_level") or "1193"),
        }

        response = requests.post(
            url,
            headers=headers,
            data=xml_body.encode("utf-8"),
            timeout=30,
        )

        response_text = response.text or ""
        ack_success = (
            "<Ack>Success</Ack>" in response_text
            or "<Ack>Warning</Ack>" in response_text
        )
        ok = response.status_code < 300 and ack_success

        return {
            "ok": ok,
            "success": ok,
            "marketplace": "ebay",
            "action": action,
            "status_code": response.status_code,
            "response_text": response_text[:4000],
            "live_write": True,
            "ebay_call": "ReviseInventoryStatus",
            "external_listing_id": item_id,
            "sku": sku,
            "quantity": quantity,
        }
