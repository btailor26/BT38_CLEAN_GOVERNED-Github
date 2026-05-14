#!/usr/bin/env python3
"""
STEP 27 - Backfill script to fix orders with zero unit_price.

This script:
1. Finds orders with unit_price = 0 or NULL
2. Attempts to get price from MarketplaceListing as fallback
3. Recalculates line_total and gross_profit

Usage:
    python scripts/backfill_order_pricing.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import MarketplaceOrder, MarketplaceListing, WarehouseStock


def backfill_order_pricing():
    """Fix orders with zero unit_price using fallback sources."""
    with app.app_context():
        print("=" * 60)
        print("STEP 27: Backfill Order Pricing")
        print("=" * 60)
        
        # Find orders with zero or null unit_price
        orders_to_fix = MarketplaceOrder.query.filter(
            MarketplaceOrder.status == 'processed',
            db.or_(
                MarketplaceOrder.unit_price == 0,
                MarketplaceOrder.unit_price.is_(None)
            )
        ).all()
        
        print(f"\nFound {len(orders_to_fix)} orders with zero/null unit_price")
        
        if not orders_to_fix:
            print("Nothing to fix!")
            return
        
        # Before state
        print("\n--- BEFORE ---")
        for order in orders_to_fix:
            print(f"  Order {order.id}: {order.marketplace_order_id} | SKU: {order.sku} | "
                  f"unit_price={order.unit_price} | line_total={order.line_total} | gross_profit={order.gross_profit}")
        
        fixed_count = 0
        for order in orders_to_fix:
            # Try to get price from MarketplaceListing
            listing = MarketplaceListing.query.filter_by(
                store_id=order.store_id,
                external_sku=order.sku
            ).first()
            
            # Also try by warehouse SKU
            if not listing and order.warehouse_stock_id:
                ws = db.session.get(WarehouseStock, order.warehouse_stock_id)
                if ws:
                    listing = MarketplaceListing.query.filter_by(
                        store_id=order.store_id,
                        warehouse_stock_id=order.warehouse_stock_id
                    ).first()
            
            if listing and listing.price and float(listing.price) > 0:
                order.unit_price = float(listing.price)
                order.line_total = order.unit_price * (order.quantity or 0)
                
                # Recalculate product cost if warehouse_stock has unit_cost
                if order.warehouse_stock_id:
                    ws = db.session.get(WarehouseStock, order.warehouse_stock_id)
                    if ws and ws.unit_cost:
                        order.product_cost = ws.unit_cost * (order.quantity or 0)
                
                order.calculate_profit()
                fixed_count += 1
                print(f"  FIXED: Order {order.id} -> unit_price={order.unit_price}, line_total={order.line_total}, gross_profit={order.gross_profit}")
            else:
                print(f"  SKIPPED: Order {order.id} - No listing price available for SKU {order.sku}")
        
        db.session.commit()
        
        # After state
        print("\n--- AFTER ---")
        for order in orders_to_fix:
            print(f"  Order {order.id}: {order.marketplace_order_id} | SKU: {order.sku} | "
                  f"unit_price={order.unit_price} | line_total={order.line_total} | gross_profit={order.gross_profit}")
        
        print(f"\n✓ Fixed {fixed_count}/{len(orders_to_fix)} orders")
        print("=" * 60)


if __name__ == '__main__':
    backfill_order_pricing()
