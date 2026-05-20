"""
BT38 GOVERNED AMAZON INVENTORY HYDRATION DRY RUN

READ ONLY
NO DATABASE WRITES
NO AUTO EXECUTION
NO ROUTE WIRING

Purpose:
- inspect what WOULD hydrate
- prove quantity mappings
- prove warehouse linkage
- prove AFN/FBA vs MFN/FBM handling

This file must not mutate live inventory.
"""

from app import db
from models import (
    AmazonFBAInventory,
    MarketplaceListing,
    WarehouseStock,
)


def run_governed_amazon_inventory_hydration_dry_run(limit=100):

    rows = (
        db.session.query(AmazonFBAInventory)
        .limit(limit)
        .all()
    )

    stats = {
        "rows_checked": 0,
        "linked_rows": 0,
        "missing_warehouse_links": 0,
        "non_zero_quantities": 0,
    }

    output = []

    for inv in rows:

        stats["rows_checked"] += 1

        qty = inv.available_quantity or 0

        if qty > 0:
            stats["non_zero_quantities"] += 1

        listing = (
            db.session.query(MarketplaceListing)
            .filter(
                MarketplaceListing.warehouse_stock_id == inv.warehouse_stock_id
            )
            .first()
        )

        if not listing:

            stats["missing_warehouse_links"] += 1

            output.append({
                "status": "missing_listing",
                "warehouse_stock_id": inv.warehouse_stock_id,
                "seller_sku": inv.seller_sku,
                "available_quantity": qty,
            })

            continue

        stats["linked_rows"] += 1

        ws = db.session.get(
            WarehouseStock,
            listing.warehouse_stock_id
        )

        output.append({
            "status": "linked",
            "seller_sku": inv.seller_sku,
            "asin": inv.asin,
            "channel": getattr(
                listing,
                "normalized_amazon_fulfillment_channel",
                None
            ),

            "amazon_quantity": qty,

            "listing": {
                "listing_id": listing.id,
                "last_marketplace_qty": getattr(
                    listing,
                    "last_marketplace_qty",
                    None
                ),
            },

            "warehouse": {
                "warehouse_stock_id": ws.id if ws else None,
                "available_quantity": (
                    ws.available_quantity if ws else None
                ),
                "sellable_quantity": (
                    ws.sellable_quantity if ws else None
                ),
            } if ws else None
        })

    return {
        "stats": stats,
        "rows": output,
    }
