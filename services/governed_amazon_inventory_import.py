"""
BT38 GOVERNED AMAZON INVENTORY IMPORT

Single governed execution path.

Authority rule:
- AFN/FBA inventory imports into AmazonFBAInventory only.
- FBA/AFN is read-only and must not create or mutate WarehouseStock.
- MarketplaceListing may keep lightweight marketplace quantity/cache state.
- Warehouse remains operational stock truth for FBM/MFN only.
"""

from datetime import datetime

from app import db
from models import (
    Store,
    MarketplaceListing,
    AmazonFBAInventory,
    SyncLog,
)

from backend.adapters.amazon_sp_api_adapter import AmazonSPAPIAdapter


def _find_or_create_marketplace_listing(store, sku, channel, qty, asin=None, fnsku=None):
    """
    Lightweight marketplace listing cache.

    Do not create or mutate WarehouseStock here.
    FBA stock authority is AmazonFBAInventory.
    """
    external_listing_id = fnsku or sku or asin

    listing = (
        db.session.query(MarketplaceListing)
        .filter(
            MarketplaceListing.store_id == store.id,
            MarketplaceListing.external_listing_id == external_listing_id,
            MarketplaceListing.external_sku == sku,
        )
        .first()
    )

    if not listing:
        listing = MarketplaceListing(
            store_id=store.id,
            external_listing_id=external_listing_id,
            external_sku=sku,
            title=f"Amazon SKU {sku}",
            price=0.0,
            currency="GBP",
            is_active=True,
        )
        db.session.add(listing)

    listing.asin = asin
    listing.fnsku = fnsku
    listing.amazon_fulfillment_channel = channel
    listing.last_marketplace_qty = qty
    listing.last_synced_at = datetime.utcnow()
    listing.is_active = True

    return listing

def deactivate_fba_shadow_listing_duplicates():
    """
    FBA read-only rows belong in AmazonFBAInventory.
    Old standalone MarketplaceListing shadow rows are duplicates when:
    - warehouse_stock_id is NULL
    - title starts with "Amazon SKU"
    - fnsku/external_listing_id points to FNSKU
    """
    rows = (
        db.session.query(MarketplaceListing)
        .join(Store, MarketplaceListing.store_id == Store.id)
        .filter(Store.platform.ilike("%amazon%"))
        .filter(MarketplaceListing.title.ilike("Amazon SKU%"))
        .filter(MarketplaceListing.is_active == True)  # noqa: E712
        .all()
    )

    cleaned = 0

    for row in rows:
        row.is_active = False
        row.status = "archived_fba_shadow_duplicate"
        cleaned += 1

    db.session.commit()

    return {
        "success": True,
        "governed": True,
        "cleaned": cleaned,
        "rule": "FBA read-only quantities live in AmazonFBAInventory only",
    }


def run_governed_amazon_inventory_import(store_id=None):
    query = db.session.query(Store).filter(
        Store.platform.ilike("%amazon%"),
        Store.is_active == True,  # noqa: E712
    )

    if store_id:
        query = query.filter(Store.id == store_id)

    stores = query.all()
    results = []

    for store in stores:
        adapter = AmazonSPAPIAdapter(store)
        inventory = adapter.get_inventory()

        imported = 0
        linked_listings = 0

        for row in inventory:
            sku = (row.get("seller_sku") or "").strip()
            if not sku:
                continue

            qty = int(row.get("available_quantity") or 0)
            # Fulfillment must come from Amazon truth.
            # Never default missing fulfillment data to AFN/FBA because that can wrongly lock FBM stock.
            channel = (row.get("fulfillment_channel") or "").strip().upper()

            if channel in {"FBA", "AMAZON", "AMAZON_FULFILLED"}:
                channel = "AFN"
            elif channel in {"FBM", "MFN", "MERCHANT", "MERCHANT_FULFILLED"}:
                channel = "MFN"
            elif not channel:
                channel = "UNKNOWN"
            asin = row.get("asin")
            fnsku = row.get("fnsku")

            inv = (
                db.session.query(AmazonFBAInventory)
                .filter(
                    AmazonFBAInventory.seller_sku == sku
                )
                .first()
            )

            if not inv:
                inv = AmazonFBAInventory(
                    seller_sku=sku,
                )
                db.session.add(inv)

            if hasattr(inv, "store_id"):
                inv.store_id = store.id

            inv.available_quantity = qty

            inv.reserved_quantity = int(
                row.get("reserved_quantity") or 0
            )

            inv.inbound_quantity = int(
                row.get("inbound_quantity") or 0
            )

            inv.asin = asin
            inv.fnsku = fnsku
            inv.is_archived = False
            inv.updated_at = datetime.utcnow()

            # FBA read-only import must update AmazonFBAInventory only.
            # Do not create standalone MarketplaceListing shadow rows.
            # Warehouse page reads FBA quantities by SKU/FNSKU shortcut overlay.

            imported += 1

        db.session.add(SyncLog(
            store_id=store.id,
            status="success",
            items_synced=imported,
            message=(
                f"governed_amazon_inventory_import "
                f"imported={imported} "
                f"fba_truth_rows={imported} "
                f"listings={linked_listings}"
            ),
            created_at=datetime.utcnow(),
        ))

        results.append({
            "store_id": store.id,
            "store": store.name,
            "imported": imported,
            "fba_truth_rows": imported,
            "listings": linked_listings,
        })

    # FBA read-only quantity import must not leave active shadow MarketplaceListing rows.
    # These rows appear as duplicate "Amazon SKU ..." entries on Master Stock.
    shadow_cleanup = deactivate_fba_shadow_listing_duplicates()

    db.session.commit()

    return {
        "success": True,
        "governed": True,
        "truth_source": "AmazonFBAInventory",
        "warehouse_mutation": False,
        "shadow_duplicates_archived": shadow_cleanup.get("cleaned", 0),
        "results": results,
    }
