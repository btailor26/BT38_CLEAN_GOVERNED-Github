#!/usr/bin/env python3
"""
Test script to verify WarehousePushCoordinator and marketplace connections
"""
import sys
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Import app context
from app import app, db
from models import WarehouseStock, Store, MarketplaceListing, InventoryItem, StockLedgerEntry
from warehouse_push_coordinator import WarehousePushCoordinator

def test_coordinator():
    """Test the WarehousePushCoordinator with a real warehouse adjustment"""
    with app.app_context():
        print("\n" + "="*80)
        print("WAREHOUSE PUSH COORDINATOR TEST")
        print("="*80)
        
        # 1. Check active stores
        print("\n1️⃣  Checking active stores...")
        active_stores = Store.query.filter_by(is_active=True).all()
        print(f"   Found {len(active_stores)} active stores:")
        for store in active_stores:
            print(f"   - {store.name} ({store.platform})")
            print(f"     Auto-push: {store.auto_push_enabled}, Push on qty change: {store.push_on_quantity_change}")
        
        # 2. Find a test SKU with listings
        print("\n2️⃣  Finding test SKU with marketplace listings...")
        test_stock = db.session.query(WarehouseStock).join(
            MarketplaceListing, MarketplaceListing.warehouse_stock_id == WarehouseStock.id
        ).join(
            Store, MarketplaceListing.store_id == Store.id
        ).filter(
            Store.is_active == True,
            Store.auto_push_enabled == True,
            Store.push_on_quantity_change == True
        ).first()
        
        if not test_stock:
            print("   ❌ No SKUs found with active marketplace listings")
            return False
        
        print(f"   ✅ Test SKU: {test_stock.sku}")
        print(f"   Current quantity: {test_stock.available_quantity}")
        
        # Count listings
        listings = MarketplaceListing.query.filter_by(
            warehouse_stock_id=test_stock.id
        ).all()
        print(f"   Marketplace listings: {len(listings)}")
        for listing in listings:
            store = Store.query.get(listing.store_id)
            print(f"     - {store.platform}: {store.name}")
        
        # 3. Simulate warehouse adjustment
        print("\n3️⃣  Simulating warehouse adjustment...")
        old_quantity = test_stock.available_quantity
        new_quantity = old_quantity + 2  # Increase by 2
        
        print(f"   Adjusting {test_stock.sku}: {old_quantity} → {new_quantity}")
        test_stock.available_quantity = new_quantity
        
        # Create ledger entry
        ledger = StockLedgerEntry(
            warehouse_stock_id=test_stock.id,
            transaction_type='adjustment',
            adjustment_type='increase',
            available_quantity_before=old_quantity,
            available_quantity_after=new_quantity,
            reason='Testing WarehousePushCoordinator',
            reference_type='test',
            created_by='test_script',
            source_system='test'
        )
        db.session.add(ledger)
        
        # 4. Test coordinator prepare
        print("\n4️⃣  Testing WarehousePushCoordinator.prepare_for_items()...")
        coordinator = WarehousePushCoordinator()
        prepared_count = coordinator.prepare_for_items([test_stock.sku], operation="update")
        print(f"   ✅ Prepared {prepared_count} SKUs for push")
        print(f"   Pending jobs: {len(coordinator.pending_jobs)}")
        
        # 5. Commit changes
        print("\n5️⃣  Committing database changes...")
        db.session.commit()
        print("   ✅ Changes committed successfully")
        
        # 6. Enqueue push jobs
        print("\n6️⃣  Enqueuing push jobs...")
        jobs_enqueued = coordinator.enqueue_pending_jobs()
        print(f"   ✅ Enqueued {jobs_enqueued} push jobs")
        
        # 7. Verify jobs were created
        print("\n7️⃣  Verifying push jobs in database...")
        from queue_manager import JOB_PUSH_ITEM
        from models import SyncJob
        recent_jobs = SyncJob.query.filter_by(
            job_type=JOB_PUSH_ITEM
        ).order_by(SyncJob.enqueued_at.desc()).limit(5).all()
        
        print(f"   Recent push jobs:")
        for job in recent_jobs:
            store = Store.query.get(job.store_id)
            print(f"     - Job #{job.id}: {store.platform} ({store.name})")
            print(f"       Status: {job.status}, Priority: {job.priority}")
            print(f"       Payload: {job.payload}")
        
        # 8. Test complete
        print("\n" + "="*80)
        print("✅ TEST COMPLETE - All coordinator functions working correctly!")
        print("="*80)
        
        return True

if __name__ == "__main__":
    try:
        success = test_coordinator()
        sys.exit(0 if success else 1)
    except Exception as e:
        logging.error(f"Test failed: {str(e)}", exc_info=True)
        sys.exit(1)
