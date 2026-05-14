#!/usr/bin/env python3
"""
STEP 28 - Backfill script to populate MarketplaceListing.price from internal sources.

This script:
1. Finds listings with price = 0 or NULL
2. Attempts fallback chain:
   a) listing.sale_price (if set)
   b) Historical MarketplaceOrder.unit_price for same SKU
   c) warehouse_stock.unit_cost
3. Sets price_missing=True if no source found

Usage:
    python scripts/backfill_listing_prices.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import MarketplaceListing, WarehouseStock, MarketplaceOrder


def backfill_listing_prices():
    """Populate MarketplaceListing.price from internal sources."""
    with app.app_context():
        print("=" * 60)
        print("STEP 28: Backfill Listing Prices (Extended Fallback)")
        print("=" * 60)
        
        # Before state
        before_zero = db.session.query(db.func.count(MarketplaceListing.id)).filter(
            db.or_(MarketplaceListing.price == 0, MarketplaceListing.price.is_(None))
        ).scalar()
        before_total = db.session.query(db.func.count(MarketplaceListing.id)).scalar()
        
        print(f"\n--- BEFORE ---")
        print(f"Total listings: {before_total}")
        print(f"Zero/NULL price: {before_zero}")
        
        # Find listings with zero or null price
        listings_to_fix = MarketplaceListing.query.filter(
            db.or_(
                MarketplaceListing.price == 0,
                MarketplaceListing.price.is_(None)
            )
        ).all()
        
        fixed_count = 0
        still_missing = 0
        source_stats = {'sale_price': 0, 'order_history': 0, 'unit_cost': 0}
        
        for listing in listings_to_fix:
            resolved_price = None
            source = None
            
            # Fallback 1: listing.sale_price (if column exists)
            sale_price_val = getattr(listing, 'sale_price', None)
            if sale_price_val and sale_price_val >= 0.99:
                resolved_price = sale_price_val
                source = 'sale_price'
            
            # Fallback 2: Historical order unit_price for this SKU (deterministic: latest by created_at, then id)
            if not resolved_price and listing.external_sku:
                order = MarketplaceOrder.query.filter(
                    MarketplaceOrder.store_id == listing.store_id,
                    MarketplaceOrder.sku == listing.external_sku,
                    MarketplaceOrder.unit_price > 0,
                    MarketplaceOrder.status == 'processed'
                ).order_by(MarketplaceOrder.created_at.desc(), MarketplaceOrder.id.desc()).first()
                
                if order and order.unit_price >= 0.99:
                    resolved_price = order.unit_price
                    source = 'order_history'
            
            # Fallback 3: warehouse_stock.unit_cost
            if not resolved_price and listing.warehouse_stock_id:
                ws = db.session.get(WarehouseStock, listing.warehouse_stock_id)
                if ws and ws.unit_cost and ws.unit_cost >= 0.99:
                    resolved_price = ws.unit_cost
                    source = 'unit_cost'
            
            if resolved_price:
                listing.price = resolved_price
                listing.price_missing = False
                fixed_count += 1
                source_stats[source] += 1
            else:
                listing.price_missing = True
                still_missing += 1
        
        db.session.commit()
        
        # After state
        after_zero = db.session.query(db.func.count(MarketplaceListing.id)).filter(
            db.or_(MarketplaceListing.price == 0, MarketplaceListing.price.is_(None))
        ).scalar()
        after_missing = db.session.query(db.func.count(MarketplaceListing.id)).filter(
            MarketplaceListing.price_missing == True
        ).scalar()
        
        print(f"\n--- AFTER ---")
        print(f"Fixed with fallback: {fixed_count}")
        print(f"  - From sale_price: {source_stats['sale_price']}")
        print(f"  - From order_history: {source_stats['order_history']}")
        print(f"  - From unit_cost: {source_stats['unit_cost']}")
        print(f"Still missing (no source): {still_missing}")
        print(f"Zero/NULL price remaining: {after_zero}")
        print(f"price_missing=True count: {after_missing}")
        
        print("=" * 60)
        return fixed_count, still_missing


if __name__ == '__main__':
    backfill_listing_prices()
