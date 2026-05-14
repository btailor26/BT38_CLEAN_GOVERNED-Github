#!/usr/bin/env python3
"""
STEP 26 - Backfill script for marketplace_orders line_total and gross_profit

This script updates existing processed orders that have line_total=0 or NULL,
calculating line_total from unit_price * quantity and calling calculate_profit().

CONSTRAINTS:
- Only affects orders with status='processed' AND (line_total IS NULL OR line_total=0)
- Does NOT call any marketplace APIs
- Does NOT change store_mode or is_active
- DB-only operation

Usage:
    python scripts/backfill_marketplace_order_totals.py
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import MarketplaceOrder, WarehouseStock


def backfill_marketplace_order_totals():
    """Backfill line_total and gross_profit for processed marketplace orders."""
    
    with app.app_context():
        print("=" * 60)
        print("STEP 26: Backfill marketplace_order line_total + gross_profit")
        print("=" * 60)
        
        # Query orders needing backfill
        orders_to_update = MarketplaceOrder.query.filter(
            MarketplaceOrder.status == 'processed',
            db.or_(
                MarketplaceOrder.line_total == None,
                MarketplaceOrder.line_total == 0
            )
        ).all()
        
        total_scanned = len(orders_to_update)
        updated = 0
        skipped = 0
        errors = 0
        
        print(f"\nScanned: {total_scanned} orders need backfill")
        print("-" * 60)
        
        for order in orders_to_update:
            try:
                unit_price = order.unit_price or 0
                quantity = order.quantity or 0
                
                # Calculate line_total
                order.line_total = unit_price * quantity
                
                # Try to get product_cost from warehouse_stock
                if order.warehouse_stock_id:
                    warehouse_stock = db.session.get(WarehouseStock, order.warehouse_stock_id)
                    if warehouse_stock and warehouse_stock.unit_cost:
                        order.product_cost = warehouse_stock.unit_cost * quantity
                
                # Calculate profit metrics
                order.calculate_profit()
                
                updated += 1
                
                if updated <= 5:
                    print(f"  Updated order {order.id}: SKU={order.sku}, qty={quantity}, "
                          f"unit_price={unit_price:.2f}, line_total={order.line_total:.2f}, "
                          f"gross_profit={order.gross_profit:.2f}")
                
            except Exception as e:
                errors += 1
                print(f"  ERROR on order {order.id}: {str(e)}")
        
        # Commit all changes
        if updated > 0:
            db.session.commit()
            print(f"\n... and {updated - 5} more orders updated" if updated > 5 else "")
        
        print("-" * 60)
        print(f"SUMMARY:")
        print(f"  Scanned:  {total_scanned}")
        print(f"  Updated:  {updated}")
        print(f"  Skipped:  {skipped}")
        print(f"  Errors:   {errors}")
        print("=" * 60)
        
        return {
            'scanned': total_scanned,
            'updated': updated,
            'skipped': skipped,
            'errors': errors
        }


if __name__ == '__main__':
    result = backfill_marketplace_order_totals()
    sys.exit(0 if result['errors'] == 0 else 1)
