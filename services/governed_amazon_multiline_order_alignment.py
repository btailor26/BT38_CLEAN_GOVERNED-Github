"""Keep Amazon order ingestion authoritative at the line-item level.

A single AmazonOrderId can contain multiple OrderItems. An earlier optimisation
stopped at the order level when any MarketplaceOrder row already existed, which
meant a webhook-created first line could permanently hide later sibling lines.

This alignment replaces only the existing Amazon import function. It keeps the
same 24-hour bounded Orders read, the same MarketplaceOrder writer and the same
stock-mutation bridge. Existing lines are hydrated but never reprocessed for
stock; Amazon's exact get_order_items response remains authoritative for finding
missing sibling lines. No worker, poller, table, marketplace write or second
order system is introduced.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def install_governed_amazon_multiline_order_alignment() -> None:
    from extensions import db
    from models import MarketplaceOrder
    from services import governed_marketplace_order_import as order_import

    original = order_import._run_amazon_order_import
    if getattr(original, "_bt38_amazon_multiline_aligned", False):
        return

    def aligned_run_amazon_order_import(store, *, source: str) -> dict[str, Any]:
        from sp_api.api import Orders
        from sp_api.base import Marketplaces

        creds = order_import._store_credentials(store)
        marketplace_id = creds.get("marketplace_id") or "A1F83G8C2ARO7P"

        client = Orders(
            marketplace=Marketplaces.UK,
            credentials=order_import._amazon_credentials(store),
        )

        last_updated_after = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).isoformat().replace("+00:00", "Z")

        response = client.get_orders(
            LastUpdatedAfter=last_updated_after,
            MarketplaceIds=[marketplace_id],
        )

        payload = response.payload or {}
        orders = payload.get("Orders") or []

        imported = 0
        created = 0
        skipped = 0
        unmatched = 0
        existing_skipped = 0
        existing_hydrated = 0
        item_read_attempts = 0
        address_read_attempts = 0
        address_read_failures = 0
        line_results = []

        allowed_statuses = {"UNSHIPPED", "PARTIALLYSHIPPED", "SHIPPED", "PENDING"}

        for order in orders:
            order_id = order_import._text(order.get("AmazonOrderId"))
            marketplace_created_at = order_import._parse_ebay_datetime(order.get("PurchaseDate"))
            order_status = order_import._text(order.get("OrderStatus")).upper()
            fulfillment_channel = order_import._text(order.get("FulfillmentChannel")).upper()

            if not order_id:
                skipped += 1
                continue

            if order_status not in allowed_statuses:
                skipped += 1
                continue

            shipped_at = None
            if order_status == "SHIPPED":
                shipped_at = (
                    order_import._parse_ebay_datetime(order.get("LastUpdateDate"))
                    or order_import._parse_ebay_datetime(order.get("LatestShipDate"))
                    or datetime.utcnow()
                )

            delivery = {
                "name": "",
                "address": "",
                "city": "",
                "postcode": "",
                "country": "",
                "phone": "",
            }
            address_error = None

            if fulfillment_channel != "AFN":
                address_read_attempts += 1
                delivery, address_error = order_import._amazon_delivery_fields(
                    client,
                    order_id,
                    order,
                )
                if address_error:
                    address_read_failures += 1

            # Existing rows prove only that one or more lines were seen. They do
            # not prove that Amazon's complete OrderItems set was persisted.
            existing_rows = (
                MarketplaceOrder.query
                .filter(MarketplaceOrder.store_id == store.id)
                .filter(MarketplaceOrder.marketplace_order_id == order_id)
                .all()
            )
            if existing_rows:
                order_import._hydrate_existing_amazon_rows(
                    existing_rows,
                    delivery=delivery,
                    shipped_at=shipped_at,
                )
                existing_hydrated += 1

            # Always ask Amazon for the exact line set, even when one sibling is
            # already persisted. upsert_governed_marketplace_order_line remains
            # the single idempotent writer for each OrderItemId/SKU.
            try:
                item_read_attempts += 1
                items_response = client.get_order_items(order_id)
                items_payload = items_response.payload or {}
                items = items_payload.get("OrderItems") or []
            except Exception as exc:
                skipped += 1
                line_results.append({
                    "success": False,
                    "skipped": True,
                    "reason": "amazon_order_items_read_failed",
                    "order_id": order_id,
                    "error": str(exc),
                })
                continue

            fulfillment_type = "FBA" if fulfillment_channel == "AFN" else "FBM"

            for item in items:
                sku = order_import._text(item.get("SellerSKU"))
                item_id = (
                    order_import._text(item.get("OrderItemId"))
                    or f"{order_id}:{sku}"
                )
                qty = order_import._safe_int(item.get("QuantityOrdered"))

                price_value = 0.0
                item_price = item.get("ItemPrice") or {}
                if isinstance(item_price, dict):
                    price_value = order_import._safe_float(item_price.get("Amount"))

                result = order_import.upsert_governed_marketplace_order_line(
                    store=store,
                    marketplace_order_id=order_id,
                    marketplace_order_item_id=item_id,
                    sku=sku,
                    quantity=qty,
                    unit_price=price_value,
                    fulfillment_type=fulfillment_type,
                    status="pending",
                    shipped_at=shipped_at,
                    ship_to_name=delivery.get("name"),
                    ship_to_address=delivery.get("address"),
                    ship_to_city=delivery.get("city"),
                    ship_to_postcode=delivery.get("postcode"),
                    ship_to_country=delivery.get("country"),
                    ship_to_phone=delivery.get("phone"),
                    marketplace_created_at=marketplace_created_at,
                    import_source=source,
                )

                if result.get("created"):
                    processing_result = order_import._process_exact_imported_order(
                        result,
                        source=f"{source}:amazon_exact_order",
                    )
                    result["processing"] = processing_result
                else:
                    existing_skipped += 1
                    result.pop("_order_row", None)
                    result["processing"] = {
                        "success": True,
                        "skipped": True,
                        "reason": "existing_line_stock_processing_skipped",
                    }

                if address_error:
                    result["address_error"] = address_error
                line_results.append(result)

                if result.get("success") and not result.get("skipped"):
                    imported += 1
                    if result.get("created"):
                        created += 1
                    if not result.get("warehouse_stock_id"):
                        unmatched += 1
                else:
                    skipped += 1

        order_import._write_sync_log(
            store,
            status="success",
            items_synced=imported,
            message=(
                f"governed_amazon_order_import imported={imported} "
                f"created={created} skipped={skipped} existing_skipped={existing_skipped} "
                f"existing_hydrated={existing_hydrated} item_read_attempts={item_read_attempts} "
                f"address_read_attempts={address_read_attempts} address_read_failures={address_read_failures} "
                f"unmatched={unmatched} window_hours=24 source={source}"
            ),
        )
        db.session.commit()

        return {
            "success": True,
            "governed": True,
            "marketplace": "amazon",
            "source": source,
            "window_hours": 24,
            "orders_seen": len(orders),
            "imported": imported,
            "created": created,
            "skipped": skipped,
            "existing_skipped": existing_skipped,
            "existing_hydrated": existing_hydrated,
            "item_read_attempts": item_read_attempts,
            "address_read_attempts": address_read_attempts,
            "address_read_failures": address_read_failures,
            "unmatched": unmatched,
            "results": line_results[:50],
        }

    aligned_run_amazon_order_import._bt38_amazon_multiline_aligned = True
    aligned_run_amazon_order_import._bt38_original = original
    order_import._run_amazon_order_import = aligned_run_amazon_order_import


install_governed_amazon_multiline_order_alignment()
