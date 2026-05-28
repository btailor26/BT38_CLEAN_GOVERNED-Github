"""
BT38 CLEAN AMAZON SP-API ADAPTER
"""

import json
import os
from datetime import datetime, timedelta

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
            "refresh_token": (
                creds.get("refresh_token")
                or os.getenv("AMAZON_REFRESH_TOKEN")
                or os.getenv("SP_API_REFRESH_TOKEN")
            ),
            # python-amazon-sp-api 1.9.48 validates this internal key as lwa_app_id.
            # The constructor receives credentials=..., not lwa_app_id=...
            "lwa_app_id": (
                creds.get("lwa_app_id")
                or creds.get("lwa_client_id")
                or creds.get("client_id")
                or os.getenv("AMAZON_LWA_CLIENT_ID")
                or os.getenv("AMAZON_LWA_APP_ID")
                or os.getenv("SP_API_LWA_CLIENT_ID")
            ),
            "lwa_client_secret": (
                creds.get("lwa_client_secret")
                or creds.get("client_secret")
                or os.getenv("AMAZON_LWA_CLIENT_SECRET")
                or os.getenv("SP_API_LWA_CLIENT_SECRET")
            ),
        }

        aws_access_key = (
            creds.get("aws_access_key")
            or creds.get("aws_access_key_id")
            or os.getenv("AMAZON_AWS_ACCESS_KEY_ID")
            or os.getenv("SP_API_AWS_ACCESS_KEY_ID")
        )
        aws_secret_key = (
            creds.get("aws_secret_key")
            or creds.get("aws_secret_access_key")
            or os.getenv("AMAZON_AWS_SECRET_ACCESS_KEY")
            or os.getenv("SP_API_AWS_SECRET_ACCESS_KEY")
        )
        role_arn = (
            creds.get("role_arn")
            or creds.get("aws_user_arn")
            or os.getenv("AMAZON_AWS_ROLE_ARN")
            or os.getenv("SP_API_ROLE_ARN")
        )

        if aws_access_key:
            credentials["aws_access_key"] = aws_access_key
        if aws_secret_key:
            credentials["aws_secret_key"] = aws_secret_key
        if role_arn:
            credentials["role_arn"] = role_arn

        self.client = Inventories(
            marketplace=Marketplaces.UK,
            credentials=credentials,
        )

    def get_inventory(self):

        rows = []
        next_token = None

        while True:
            kwargs = {
                "details": True,
                "granularityType": "Marketplace",
                "granularityId": (self.creds.get("marketplace_id") or "A1F83G8C2ARO7P"),
                "startDateTime": (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z",
            }

            if next_token:
                kwargs["nextToken"] = next_token

            response = self.client.get_inventory_summary_marketplace(**kwargs)

            payload = response.payload or {}
            rows.extend(payload.get("inventorySummaries") or [])

            pagination = payload.get("pagination") or {}
            next_token = (
                pagination.get("nextToken")
                or payload.get("nextToken")
                or payload.get("NextToken")
            )

            if not next_token:
                break

            if len(rows) >= 5000:
                break

        def quantity_value(value, nested_key=None):
            if isinstance(value, dict):
                if nested_key:
                    return int(value.get(nested_key) or 0)
                return 0
            return int(value or 0)

        normalized = []

        for row in rows:

            inventory_details = (
                row.get("inventoryDetails") or {}
            )

            fulfillable = inventory_details.get(
                "fulfillableQuantity"
            )

            if fulfillable is None:
                fulfillable = row.get("totalQuantity") or 0

            normalized.append({
                "seller_sku": row.get("sellerSku"),
                "asin": row.get("asin"),
                "fnsku": row.get("fnSku"),
                "condition": row.get("condition"),
                "available_quantity": quantity_value(fulfillable),
                "reserved_quantity": quantity_value(
                    inventory_details.get("reservedQuantity"),
                    "totalReservedQuantity",
                ),
                "inbound_quantity": quantity_value(
                    inventory_details.get("inboundWorkingQuantity")
                ) + quantity_value(
                    inventory_details.get("inboundShippedQuantity")
                ) + quantity_value(
                    inventory_details.get("inboundReceivingQuantity")
                ),
                "fulfillment_channel": row.get("fulfillmentChannel") or row.get("fulfillment_channel"),
                "title": row.get("productName") or row.get("title"),
                "raw": row,
            })

        return normalized
