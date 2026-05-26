"""
BT38 CLEAN AMAZON SP-API ADAPTER
"""

import json
from datetime import datetime

from sp_api.api import Inventories
from sp_api.base import Marketplaces


class AmazonSPAPIAdapter:

    def __init__(self, store):

        self.store = store

        creds = store.api_key or {}

        if isinstance(creds, str):
            try:
                creds = json.loads(creds)
            except Exception:
                creds = {}

        self.creds = creds

        credentials = {
            "refresh_token": creds.get("refresh_token"),
            "lwa_client_id": (
                creds.get("lwa_client_id")
                or creds.get("lwa_app_id")
                or creds.get("client_id")
            ),
            "lwa_client_secret": (
                creds.get("lwa_client_secret")
                or creds.get("client_secret")
            ),
        }

        if creds.get("aws_access_key"):
            credentials["aws_access_key"] = creds.get("aws_access_key")
        if creds.get("aws_secret_key"):
            credentials["aws_secret_key"] = creds.get("aws_secret_key")
        if creds.get("role_arn"):
            credentials["role_arn"] = creds.get("role_arn")

        self.client = Inventories(
            marketplace=Marketplaces.UK,
            credentials=credentials,
        )

    def get_inventory(self):

        response = self.client.get_inventory_summary_marketplace()

        payload = response.payload or {}

        rows = payload.get("inventorySummaries") or []

        normalized = []

        for row in rows:

            inventory_details = (
                row.get("inventoryDetails") or {}
            )

            fulfillable = (
                inventory_details.get(
                    "fulfillableQuantity"
                ) or 0
            )

            normalized.append({
                "seller_sku": row.get("sellerSku"),
                "asin": row.get("asin"),
                "fnsku": row.get("fnSku"),
                "available_quantity": int(fulfillable),
                "fulfillment_channel": (
                    "AFN"
                    if row.get("fnSku")
                    else "MFN"
                ),
                "raw": row,
                "synced_at": (
                    datetime.utcnow().isoformat()
                ),
            })

        return normalized
