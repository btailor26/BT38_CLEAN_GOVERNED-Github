"""
Marketplace Order Processor - Handles idempotent order processing with row-level locking.

This module prevents overselling in multi-channel scenarios by:
1. Using database row-level locking (SELECT FOR UPDATE) to prevent race conditions
2. Tracking marketplace orders with idempotency keys to prevent duplicate processing
3. Using optimistic locking (stock_version) as a secondary safety check
4. Creating comprehensive audit trails via StockLedgerEntry

Critical for production: Ensures two simultaneous sales on different marketplaces
cannot both succeed if only one unit is available.

Phase 1 Auto-Sync: Also provides centralized order import from Amazon MFN and eBay.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List
from sqlalchemy import select
from app import db
from models import WarehouseStock, MarketplaceOrder, StockLedgerEntry, Store, SyncLog, SyncJob, MarketplaceListing

logger = logging.getLogger(__name__)


class MarketplaceOrderProcessor:
    """
    Processes marketplace orders with pessimistic locking to prevent overselling.
    
    Thread-safe order processing flow:
    1. Check idempotency (has this order been processed before?)
    2. Acquire row lock on WarehouseStock (SELECT FOR UPDATE)
    3. Verify sufficient stock available
    4. Decrement stock with version check
    5. Create MarketplaceOrder and StockLedgerEntry records
    6. Commit transaction (releases lock)
    """
    
    @staticmethod
    def process_order(
        store_id: int,
        marketplace_order_id: str,
        sku: str,
        quantity: int,
        marketplace_item_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Tuple[bool, str, Optional[MarketplaceOrder]]:
        """
        Process a marketplace order with idempotency and row-level locking.
        
        Args:
            store_id: Store ID where the order originated
            marketplace_order_id: External marketplace order ID
            sku: Product SKU
            quantity: Quantity sold
            marketplace_item_id: Optional item ID for multi-item orders
            notes: Optional notes for audit trail
            
        Returns:
            Tuple of (success: bool, message: str, order: MarketplaceOrder or None)
            
        Example:
            success, msg, order = MarketplaceOrderProcessor.process_order(
                store_id=1,
                marketplace_order_id='eBay-12345',
                sku='TEST-SKU-001',
                quantity=2
            )
        """
        try:
            # Step 1: Check idempotency - prevent duplicate processing
            idempotency_key = MarketplaceOrder.generate_idempotency_key(
                store_id, marketplace_order_id, sku, marketplace_item_id
            )
            
            existing = MarketplaceOrder.query.filter_by(idempotency_key=idempotency_key).first()
            if existing:
                if existing.status == 'processed':
                    logger.info(f"Order already processed: {idempotency_key}")
                    return True, f"Order already processed (duplicate)", existing
                elif existing.status == 'failed':
                    logger.warning(f"Retrying failed order: {idempotency_key}")
                    # Allow retry of failed orders
                else:
                    logger.info(f"Order in status '{existing.status}': {idempotency_key}")
                    return False, f"Order already exists with status: {existing.status}", existing
            
            # Step 2: Acquire row-level lock on warehouse stock (pessimistic locking)
            # This prevents concurrent transactions from modifying the same SKU
            warehouse_stock = db.session.execute(
                select(WarehouseStock)
                .filter_by(sku=sku)
                .with_for_update()  # SELECT FOR UPDATE - blocks other transactions
            ).scalar_one_or_none()
            
            if not warehouse_stock:
                logger.warning(f"SKU not found in warehouse: {sku}")
                # Create failed order record
                failed_order = MarketplaceOrder(
                    store_id=store_id,
                    marketplace_order_id=marketplace_order_id,
                    marketplace_order_item_id=marketplace_item_id,
                    sku=sku,
                    quantity=quantity,
                    status='failed',
                    error_message=f'SKU {sku} not found in warehouse',
                    idempotency_key=idempotency_key
                )
                db.session.add(failed_order)
                db.session.commit()
                return False, f"SKU {sku} not found in warehouse", failed_order
            
            # GROUP RESOLUTION: If in a group, use PRIMARY warehouse stock for decrement
            # Rule G5: Sales decrement the primary source, then push to all group listings
            original_warehouse_stock = warehouse_stock
            primary_sku_info = ""
            from group_resolution import get_primary_warehouse_stock
            if warehouse_stock.master_product_group_id:
                primary = get_primary_warehouse_stock(warehouse_stock.master_product_group_id)
                if primary and primary.id != warehouse_stock.id:
                    primary_sku_info = f" (via primary SKU: {primary.sku})"
                    # Re-acquire lock on primary warehouse stock
                    warehouse_stock = db.session.execute(
                        select(WarehouseStock)
                        .filter_by(id=primary.id)
                        .with_for_update()
                    ).scalar_one()
                    logger.info(f"[GROUP_SYNC] Sale for {sku} will decrement primary {warehouse_stock.sku} in group {warehouse_stock.master_product_group_id}")
            
            # Step 3: Calculate sellable quantity and verify stock
            sellable_qty = warehouse_stock.sellable_quantity
            
            if sellable_qty < quantity:
                logger.warning(
                    f"Insufficient stock for {sku}: requested={quantity}, "
                    f"sellable={sellable_qty}, available={warehouse_stock.available_quantity}"
                )
                # Create failed order record
                failed_order = MarketplaceOrder(
                    store_id=store_id,
                    marketplace_order_id=marketplace_order_id,
                    marketplace_order_item_id=marketplace_item_id,
                    sku=sku,
                    warehouse_stock_id=warehouse_stock.id,
                    quantity=quantity,
                    status='failed',
                    error_message=f'Insufficient stock: requested {quantity}, available {sellable_qty}',
                    idempotency_key=idempotency_key
                )
                db.session.add(failed_order)
                db.session.commit()
                return False, f"Insufficient stock: {sellable_qty} available, {quantity} requested", failed_order
            
            # Step 4: Decrement stock with optimistic locking check (secondary safety)
            old_version = warehouse_stock.stock_version
            warehouse_stock.available_quantity -= quantity
            warehouse_stock.stock_version += 1
            warehouse_stock.updated_at = datetime.utcnow()
            
            # Step 5: Create ledger entry for audit trail
            ledger_entry = StockLedgerEntry(
                warehouse_stock_id=warehouse_stock.id,
                transaction_type='marketplace_sale',
                adjustment_type='decrease',
                available_quantity_before=warehouse_stock.available_quantity + quantity,
                available_quantity_after=warehouse_stock.available_quantity,
                reserved_quantity_before=warehouse_stock.reserved_quantity,
                reserved_quantity_after=warehouse_stock.reserved_quantity,
                allocated_quantity_before=warehouse_stock.allocated_quantity,
                allocated_quantity_after=warehouse_stock.allocated_quantity,
                on_order_quantity_before=warehouse_stock.on_order_quantity,
                on_order_quantity_after=warehouse_stock.on_order_quantity,
                pending_receipt_qty_before=warehouse_stock.pending_receipt_qty,
                pending_receipt_qty_after=warehouse_stock.pending_receipt_qty,
                quarantined_quantity_before=warehouse_stock.quarantined_quantity,
                quarantined_quantity_after=warehouse_stock.quarantined_quantity,
                reason=notes or f'Sale from marketplace order {marketplace_order_id}',
                reference_type='marketplace_order',
                reference_id=marketplace_order_id,
                created_by='system',
                source_system='marketplace',
                update_source='marketplace_sale'
            )
            db.session.add(ledger_entry)
            db.session.flush()  # Get ledger_entry.id
            
            # Step 6: Create marketplace order record
            order = MarketplaceOrder(
                store_id=store_id,
                marketplace_order_id=marketplace_order_id,
                marketplace_order_item_id=marketplace_item_id,
                sku=sku,
                warehouse_stock_id=warehouse_stock.id,
                quantity=quantity,
                status='processed',
                processed_at=datetime.utcnow(),
                idempotency_key=idempotency_key,
                ledger_entry_id=ledger_entry.id
            )
            
            # Note: line_total and profit are calculated after unit_price is set by the importer
            # See OrderImportService._process_single_order for the calculation
            
            db.session.add(order)
            
            # Step 7: GROUP ENFORCEMENT - Prepare push to ALL linked FBM listings BEFORE commit
            # When a sale happens on ANY marketplace, ALL linked listings MUST be updated
            from warehouse_push_coordinator import WarehousePushCoordinator
            coordinator = WarehousePushCoordinator()
            coordinator.prepare_for_items([sku], operation="update")
            
            # Step 8: Commit transaction (releases lock)
            db.session.commit()
            
            logger.info(
                f"Order processed successfully: {idempotency_key} | "
                f"SKU={sku}, qty={quantity}, version {old_version}→{warehouse_stock.stock_version}"
            )
            
            # Step 9: GROUP ENFORCEMENT - Push to ALL linked listings AFTER commit
            # This ensures all marketplaces reflect the same quantity after sale
            try:
                jobs_enqueued = coordinator.enqueue_pending_jobs()
                if jobs_enqueued > 0:
                    logger.info(f"[GROUP_ENFORCE] Sale cascade: Queued {jobs_enqueued} push jobs for SKU {sku} to sync all marketplaces")
            except Exception as push_err:
                logger.warning(f"Group push hook failed (non-fatal): {push_err}")
            
            return True, f"Order processed successfully", order
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error processing order {marketplace_order_id} for SKU {sku}: {str(e)}")
            return False, f"Error processing order: {str(e)}", None
    
    @staticmethod
    def get_order_status(store_id: int, marketplace_order_id: str, sku: str, 
                        marketplace_item_id: Optional[str] = None) -> Optional[MarketplaceOrder]:
        """
        Check if an order has been processed.
        
        Returns:
            MarketplaceOrder record if found, None otherwise
        """
        idempotency_key = MarketplaceOrder.generate_idempotency_key(
            store_id, marketplace_order_id, sku, marketplace_item_id
        )
        return MarketplaceOrder.query.filter_by(idempotency_key=idempotency_key).first()
    
    @staticmethod
    def cancel_order(order_id: int, reason: str) -> Tuple[bool, str]:
        """
        Cancel a marketplace order and restore stock.
        
        This is used when a marketplace order is cancelled or refunded.
        """
        try:
            order = MarketplaceOrder.query.get(order_id)
            if not order:
                return False, "Order not found"
            
            if order.status == 'cancelled':
                return True, "Order already cancelled"
            
            if order.status != 'processed':
                # Just mark as cancelled if not processed
                order.status = 'cancelled'
                order.error_message = reason
                order.updated_at = datetime.utcnow()
                db.session.commit()
                return True, "Order cancelled (was not processed)"
            
            # Restore stock with row-level locking
            if order.warehouse_stock_id:
                warehouse_stock = db.session.execute(
                    select(WarehouseStock)
                    .filter_by(id=order.warehouse_stock_id)
                    .with_for_update()
                ).scalar_one_or_none()
                
                if warehouse_stock:
                    # Restore quantity
                    warehouse_stock.available_quantity += order.quantity
                    warehouse_stock.stock_version += 1
                    warehouse_stock.updated_at = datetime.utcnow()
                    
                    # Create reversal ledger entry
                    ledger_entry = StockLedgerEntry(
                        warehouse_stock_id=warehouse_stock.id,
                        transaction_type='marketplace_refund',
                        adjustment_type='increase',
                        available_quantity_before=warehouse_stock.available_quantity - order.quantity,
                        available_quantity_after=warehouse_stock.available_quantity,
                        reserved_quantity_before=warehouse_stock.reserved_quantity,
                        reserved_quantity_after=warehouse_stock.reserved_quantity,
                        allocated_quantity_before=warehouse_stock.allocated_quantity,
                        allocated_quantity_after=warehouse_stock.allocated_quantity,
                        on_order_quantity_before=warehouse_stock.on_order_quantity,
                        on_order_quantity_after=warehouse_stock.on_order_quantity,
                        pending_receipt_qty_before=warehouse_stock.pending_receipt_qty,
                        pending_receipt_qty_after=warehouse_stock.pending_receipt_qty,
                        quarantined_quantity_before=warehouse_stock.quarantined_quantity,
                        quarantined_quantity_after=warehouse_stock.quarantined_quantity,
                        reason=f'Refund for order {order.marketplace_order_id}',
                        notes=reason,
                        reference_type='marketplace_order',
                        reference_id=str(order.id),
                        created_by='system',
                        source_system='marketplace',
                        update_source='marketplace_refund'
                    )
                    db.session.add(ledger_entry)
            
            # Mark order as cancelled
            order.status = 'cancelled'
            order.error_message = reason
            order.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            logger.info(f"Order cancelled: {order.marketplace_order_id} | {reason}")
            return True, "Order cancelled and stock restored"
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error cancelling order {order_id}: {str(e)}")
            return False, f"Error cancelling order: {str(e)}"


# ==============================
# Phase 1: Auto-Sync Order Import
# ==============================

class OrderImportService:
    """
    Centralized order import service for Auto-Sync Engine Phase 1.
    Polls Amazon MFN and eBay for new orders, processes them with idempotency,
    and logs results to SyncJob/SyncLog.
    """
    
    @staticmethod
    def import_orders_for_store(store: Store, hours_back: int = 24) -> Dict:
        """
        Import orders for a single store.
        
        Args:
            store: Store object to import orders from
            hours_back: How many hours back to fetch orders (default 24)
        
        Returns:
            Dict with import results
        """
        if not store.is_active:
            return {"success": False, "store_id": store.id, "error": "Store is not active", "imported": 0, "skipped": 0}
        
        created_after = (datetime.utcnow() - timedelta(hours=hours_back)).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        if store.platform.lower() == 'amazon':
            return OrderImportService._import_amazon_orders(store, created_after)
        elif store.platform.lower() == 'ebay':
            return OrderImportService._import_ebay_orders(store, created_after)
        else:
            return {"success": False, "store_id": store.id, "error": f"Unsupported platform: {store.platform}", "imported": 0, "skipped": 0}
    
    @staticmethod
    def _import_amazon_orders(store: Store, created_after: str) -> Dict:
        """Import MFN orders from Amazon"""
        from amazon_service import AmazonAPIService
        
        result = {
            "success": False,
            "store_id": store.id,
            "store_name": store.name,
            "platform": "amazon",
            "imported": 0,
            "skipped": 0,
            "failed": 0,
            "orders": [],
            "error": None
        }
        
        try:
            # Check if FBM sync is enabled (we only import MFN/FBM orders)
            if not store.fbm_sync_enabled:
                result["error"] = "FBM sync not enabled for this store"
                logger.info(f"Skipping order import for {store.name}: FBM sync not enabled")
                return result
            
            # Fetch orders from Amazon
            api = AmazonAPIService()
            orders_result = api.get_mfn_orders(store, created_after=created_after)
            
            if not orders_result.get('success'):
                error_msg = orders_result.get('error', 'Unknown error')
                result["error"] = error_msg
                
                # AMAZON-ORDER-SYNC-THROTTLE-FIX-008: Handle rate limiting gracefully
                # Don't log as 'failed' for throttling - it's expected behavior
                is_rate_limited = 'rate limit' in error_msg.lower() or '429' in str(error_msg)
                
                if is_rate_limited:
                    # Log as throttled (warning level), not failure
                    logger.warning(f"[THROTTLE] Amazon Orders API rate limited for {store.name} - will retry next cycle")
                    OrderImportService._log_import(store, 'throttled', error_msg, 0)
                    # Return success=True to prevent failure escalation
                    result["success"] = True  # Throttling is not a failure
                else:
                    OrderImportService._log_import(store, 'failed', error_msg, 0)
                return result
            
            orders = orders_result.get('orders', [])
            
            # Process each order
            for order_data in orders:
                import_result = OrderImportService._process_order_item(store, order_data)
                
                if import_result['status'] == 'imported':
                    result["imported"] += 1
                    result["orders"].append(import_result)
                elif import_result['status'] == 'skipped':
                    result["skipped"] += 1
                else:
                    result["failed"] += 1
            
            result["success"] = True
            
            # Log to SyncLog
            msg = f"Imported {result['imported']} orders, skipped {result['skipped']}, failed {result['failed']}"
            OrderImportService._log_import(store, 'completed', msg, result['imported'])
            
            logger.info(f"Amazon order import for {store.name}: {msg}")
            return result
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error importing Amazon orders for {store.name}: {str(e)}")
            OrderImportService._log_import(store, 'failed', str(e), 0)
            return result
    
    @staticmethod
    def _import_ebay_orders(store: Store, created_after: str) -> Dict:
        """Import orders from eBay"""
        from ebay_service import get_ebay_orders
        
        result = {
            "success": False,
            "store_id": store.id,
            "store_name": store.name,
            "platform": "ebay",
            "imported": 0,
            "skipped": 0,
            "failed": 0,
            "orders": [],
            "error": None
        }
        
        logger.info(f"[EBAY_SYNC_START] store_id={store.id} store_name={store.name} created_after={created_after}")
        
        try:
            # Fetch orders from eBay
            orders_result = get_ebay_orders(store, created_after=created_after)
            
            if not orders_result.get('success'):
                result["error"] = orders_result.get('error', 'Unknown error')
                OrderImportService._log_import(store, 'failed', result["error"], 0)
                return result
            
            orders = orders_result.get('orders', [])
            
            logger.info(f"[EBAY_SYNC_FETCHED] store_id={store.id} orders_from_api={len(orders)}")
            
            # Process each order
            for order_data in orders:
                import_result = OrderImportService._process_order_item(store, order_data)
                
                if import_result['status'] == 'imported':
                    result["imported"] += 1
                    result["orders"].append(import_result)
                elif import_result['status'] == 'skipped':
                    result["skipped"] += 1
                else:
                    result["failed"] += 1
            
            result["success"] = True
            
            # Log to SyncLog
            msg = f"Imported {result['imported']} orders, skipped {result['skipped']}, failed {result['failed']}"
            OrderImportService._log_import(store, 'completed', msg, result['imported'])
            
            logger.info(f"[EBAY_SYNC_END] store_id={store.id} imported={result['imported']} skipped={result['skipped']} failed={result['failed']}")
            return result
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error importing eBay orders for {store.name}: {str(e)}")
            OrderImportService._log_import(store, 'failed', str(e), 0)
            return result
    
    @staticmethod
    def _process_order_item(store: Store, order_data: Dict) -> Dict:
        """
        Process a single order item. Maps SKU to warehouse and decrements stock.
        
        Returns:
            Dict with 'status' ('imported', 'skipped', 'failed') and details
        """
        sku = order_data.get('sku', '')
        quantity = order_data.get('quantity', 0)
        marketplace_order_id = order_data.get('marketplace_order_id', '')
        marketplace_item_id = order_data.get('marketplace_order_item_id', '')
        
        # Validate data
        if not sku or quantity <= 0:
            return {"status": "failed", "reason": "Invalid SKU or quantity", "sku": sku}
        
        # Check idempotency first (before looking up warehouse)
        idempotency_key = MarketplaceOrder.generate_idempotency_key(
            store.id, marketplace_order_id, sku, marketplace_item_id
        )
        existing = MarketplaceOrder.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return {"status": "skipped", "reason": f"Already processed (status: {existing.status})", "order_id": marketplace_order_id, "sku": sku}
        
        # Map SKU to warehouse stock via MarketplaceListing
        warehouse_sku = OrderImportService._resolve_warehouse_sku(store.id, sku, order_data.get('external_item_id'))
        
        if not warehouse_sku:
            # Create order record with failed status but don't decrement stock
            try:
                failed_order = MarketplaceOrder(
                    store_id=store.id,
                    marketplace_order_id=marketplace_order_id,
                    marketplace_order_item_id=marketplace_item_id,
                    sku=sku,
                    quantity=quantity,
                    fulfillment_type='FBM',
                    unit_price=order_data.get('item_price', 0),
                    status='failed',
                    error_message=f'SKU {sku} not linked to warehouse',
                    idempotency_key=idempotency_key
                )
                db.session.add(failed_order)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Could not record failed order for SKU {sku}: {str(e)}")
            
            logger.warning(
                f"[SKU_UNLINKED] store_id={store.id} order_id={marketplace_order_id} "
                f"external_sku={sku} quantity={quantity} reason=SKU_NOT_LINKED"
            )
            
            return {"status": "failed", "reason": f"SKU {sku} not linked to warehouse", "order_id": marketplace_order_id, "sku": sku}
        
        # Process order with stock decrement
        success, message, order = MarketplaceOrderProcessor.process_order(
            store_id=store.id,
            marketplace_order_id=marketplace_order_id,
            sku=warehouse_sku,
            quantity=quantity,
            marketplace_item_id=marketplace_item_id,
            notes=f"Auto-imported from {store.platform}"
        )
        
        if success:
            # Update order with additional data and calculate totals
            if order:
                # Get unit_price from order payload
                unit_price = order_data.get('item_price', 0) or 0
                
                # PRICING ENRICHMENT: If unit_price is 0, try fallback sources
                if unit_price == 0:
                    logger.warning(f"[PRICING_GAP] Zero unit_price for order {marketplace_order_id} SKU {sku} - attempting fallback")
                    
                    # Fallback 1: Try to get price from MarketplaceListing
                    listing = MarketplaceListing.query.filter_by(
                        store_id=store.id,
                        external_sku=sku
                    ).first()
                    if listing and listing.price and float(listing.price) > 0:
                        unit_price = float(listing.price)
                        logger.info(f"[PRICING_GAP] Used MarketplaceListing price fallback: {unit_price} for SKU {sku}")
                    else:
                        logger.warning(f"[PRICING_GAP] No fallback price available for order {marketplace_order_id} SKU {sku}")
                
                order.unit_price = unit_price
                order.fulfillment_type = 'FBM'
                
                # Calculate line_total and profit metrics now that unit_price is set
                order.line_total = (order.unit_price or 0) * (order.quantity or 0)
                # Set product_cost from warehouse_stock if available
                if order.warehouse_stock_id:
                    warehouse_stock = db.session.get(WarehouseStock, order.warehouse_stock_id)
                    if warehouse_stock and warehouse_stock.unit_cost:
                        order.product_cost = warehouse_stock.unit_cost * (order.quantity or 0)
                order.calculate_profit()
                
                db.session.commit()
            
            return {
                "status": "imported",
                "order_id": marketplace_order_id,
                "sku": warehouse_sku,
                "quantity": quantity,
                "message": message
            }
        else:
            return {
                "status": "failed",
                "reason": message,
                "order_id": marketplace_order_id,
                "sku": sku
            }
    
    @staticmethod
    def _resolve_warehouse_sku(store_id: int, external_sku: str, external_item_id: str = None) -> Optional[str]:
        """
        Resolve external SKU to warehouse SKU via MarketplaceListing.
        Returns warehouse SKU if linked, None otherwise.
        """
        try:
            # Try to find MarketplaceListing by external_sku
            listing = MarketplaceListing.query.filter_by(
                store_id=store_id,
                external_sku=external_sku
            ).first()
            
            # If not found by SKU, try by external_listing_id (ItemID for eBay)
            if not listing and external_item_id:
                listing = MarketplaceListing.query.filter_by(
                    store_id=store_id,
                    external_listing_id=external_item_id
                ).first()
            
            if listing and listing.warehouse_stock_id:
                # Get the warehouse SKU
                warehouse = WarehouseStock.query.get(listing.warehouse_stock_id)
                if warehouse:
                    return warehouse.sku
            
            # SKU-LOCKDOWN-001: Direct warehouse fallback REMOVED
            # Stock decrements ONLY allowed via explicit MarketplaceListing linkage
            # Unlinked SKUs are logged at [SKU_UNLINKED] and rejected by caller
            return None
            
        except Exception as e:
            logger.warning(f"Error resolving warehouse SKU for {external_sku}: {str(e)}")
            return None
    
    @staticmethod
    def _log_import(store: Store, status: str, message: str, items_count: int):
        """Log order import to SyncLog"""
        try:
            log = SyncLog(
                store_id=store.id,
                status=status,
                message=f"[Order Import] {message}",
                items_synced=items_count,
                created_at=datetime.utcnow()
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Failed to log order import for store {store.id}: {str(e)}")
    
    @staticmethod
    def run_scheduled_import(hours_back: int = 24) -> Dict:
        """
        Run order import for all active stores. Called by scheduler.
        
        Args:
            hours_back: How many hours back to fetch orders
        
        Returns:
            Dict with summary of all imports
        """
        results = {
            "success": True,
            "stores_processed": 0,
            "total_imported": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "store_results": [],
            "errors": []
        }
        
        try:
            # Get all active Amazon and eBay stores
            stores = Store.query.filter(
                Store.is_active == True,
                Store.platform.in_(['Amazon', 'amazon', 'eBay', 'ebay'])
            ).all()
            
            for store in stores:
                try:
                    store_result = OrderImportService.import_orders_for_store(store, hours_back)
                    results["store_results"].append(store_result)
                    results["stores_processed"] += 1
                    results["total_imported"] += store_result.get('imported', 0)
                    results["total_skipped"] += store_result.get('skipped', 0)
                    results["total_failed"] += store_result.get('failed', 0)
                    
                    if store_result.get('error'):
                        results["errors"].append(f"{store.name}: {store_result['error']}")
                        
                except Exception as e:
                    results["errors"].append(f"{store.name}: {str(e)}")
                    logger.error(f"Error processing store {store.name}: {str(e)}")
            
            logger.info(f"Scheduled order import complete: {results['stores_processed']} stores, {results['total_imported']} orders imported")
            return results
            
        except Exception as e:
            results["success"] = False
            results["errors"].append(str(e))
            logger.error(f"Scheduled order import failed: {str(e)}")
            return results
