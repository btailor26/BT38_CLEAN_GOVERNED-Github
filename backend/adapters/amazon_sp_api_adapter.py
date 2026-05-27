"""
BT38 CLEAN AMAZON SP-API ADAPTER
"""

import json
import os
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
            or os.getenv("AWS_ACCESS_KEY_ID")
            or os.getenv("AMAZON_AWS_ACCESS_KEY_ID")
            or os.getenv("SP_API_AWS_ACCESS_KEY_ID")
        )
        aws_secret_key = (
            creds.get("aws_secret_key")
            or creds.get("aws_secret_access_key")
            or os.getenv("AWS_SECRET_ACCESS_KEY")
            or os.getenv("AMAZON_AWS_SECRET_ACCESS_KEY")
            or os.getenv("SP_API_AWS_SECRET_ACCESS_KEY")
        )
        role_arn = (
            creds.get("role_arn")
            or creds.get("aws_user_arn")
            or os.getenv("AWS_ROLE_ARN")
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
        response = self.client.get_inventory_summary_marketplace()
        payload = response.payload if hasattr(response, "payload") else response
        rows = payload.get("inventorySummaries") or []

        mapped = []

        def as_int(value):
            try:
                return int(value or 0)
            except Exception:
                return 0

        for row in rows:
            inventory_details = row.get("inventoryDetails") or {}

            fulfillable = as_int(
                row.get("fulfillableQuantity")
                or inventory_details.get("fulfillableQuantity")
                or inventory_details.get("afnFulfillableQuantity")
            )

            reserved = as_int(
                row.get("reservedQuantity")
                or inventory_details.get("reservedQuantity")
                or inventory_details.get("afnReservedQuantity")
            )

            inbound_working = as_int(
                row.get("inboundWorkingQuantity")
                or inventory_details.get("inboundWorkingQuantity")
                or inventory_details.get("afnInboundWorkingQuantity")
            )

            inbound_shipped = as_int(
                row.get("inboundShippedQuantity")
                or inventory_details.get("inboundShippedQuantity")
                or inventory_details.get("afnInboundShippedQuantity")
            )

            inbound_receiving = as_int(
                row.get("inboundReceivingQuantity")
                or inventory_details.get("inboundReceivingQuantity")
                or inventory_details.get("afnInboundReceivingQuantity")
            )

            unfulfillable = as_int(
                row.get("unfulfillableQuantity")
                or inventory_details.get("unfulfillableQuantity")
                or inventory_details.get("afnUnfulfillableQuantity")
            )

            researching = as_int(
                row.get("researchingQuantity")
                or inventory_details.get("researchingQuantity")
                or inventory_details.get("afnResearchingQuantity")
            )

            inbound_total = inbound_working + inbound_shipped + inbound_receiving
            on_hand = fulfillable + reserved + unfulfillable + researching

            mapped.append({
                "seller_sku": row.get("sellerSku") or row.get("seller_sku") or row.get("sku"),
                "asin": row.get("asin"),
                "fnsku": row.get("fnSku") or row.get("fnsku"),
                "title": row.get("productName") or row.get("title"),
                "available_quantity": fulfillable,
                "reserved_quantity": reserved,
                "inbound_quantity": inbound_total,
                "inbound_working": inbound_working,
                "inbound_shipped": inbound_shipped,
                "inbound_receiving": inbound_receiving,
                "unfulfillable_quantity": unfulfillable,
                "researching_quantity": researching,
                "on_hand_quantity": on_hand,
                "fulfillment_channel": row.get("fulfillmentChannel") or row.get("fulfillment_channel") or "AFN",
            })

        return mapped
