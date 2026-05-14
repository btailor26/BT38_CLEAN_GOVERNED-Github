"""
Warehouse Push Coordinator

Coordinates marketplace pushes from warehouse operations using the unified two-step queue-based pattern:
1. prepare_for_items() - Collect SKUs before commit
2. enqueue_pending_jobs() - Enqueue jobs after successful commit

This module provides separation of concerns allowing both web routes and service-layer code
to trigger marketplace pushes using the same reliable pattern.

GROUP RESOLUTION:
When a warehouse stock belongs to a MasterProductGroup, the coordinator expands to push
to ALL listings across ALL group members. This ensures consistent inventory across the group.
"""

import logging
from typing import List, Tuple, Set
from app import db
from models import InventoryItem, Store, WarehouseStock, MarketplaceListing, Warehouse
from services.go_live_guard import guard_store_object


class WarehousePushCoordinator:
    """
    Coordinates marketplace pushes for warehouse operations.
    
    Usage:
        coordinator = WarehousePushCoordinator()
        coordinator.prepare_for_items([sku1, sku2, sku3], operation="update")
        db.session.commit()
        coordinator.enqueue_pending_jobs()
    """
    
    def __init__(self):
        """Initialize the coordinator"""
        self.pending_jobs = []  # List of (item_id, stores) tuples
        
    def prepare_for_items(self, skus: List[str], operation: str = "update") -> int:
        """
        Prepare warehouse stock and identify stores for push for multiple SKUs.
        
        Call this BEFORE committing the transaction.
        
        Args:
            skus: List of SKU strings to prepare
            operation: Type of operation ("create", "update", "delete")
        
        Returns:
            int: Number of items prepared for push
        """
        prepared_count = 0
        
        for sku in skus:
            try:
                # Get the inventory item (may be None for warehouse-only SKUs)
                item = InventoryItem.query.filter_by(sku=sku).first()
                
                # Prepare warehouse stock and get eligible stores
                # Works with or without InventoryItem - uses SKU directly
                stores_to_push, warehouse_stock = self._prepare_warehouse_push_by_sku(sku, operation)
                
                # Only count and add job if we have both stores and warehouse_stock
                if stores_to_push and warehouse_stock:
                    # Store item_id (if available), warehouse_stock_id, sku, and is_group_controlled for payload
                    item_id = item.id if item else None
                    is_group_controlled = getattr(warehouse_stock, 'is_group_controlled', False) or False
                    self.pending_jobs.append((item_id, stores_to_push, warehouse_stock.id, sku, is_group_controlled))
                    prepared_count += 1
                    logging.debug(f"Prepared {sku} for push to {len(stores_to_push)} stores (is_group_controlled={is_group_controlled})")
                    
            except Exception as e:
                logging.error(f"Error preparing push for SKU {sku}: {str(e)}")
                continue
        
        return prepared_count
    
    def enqueue_pending_jobs(self) -> int:
        """
        Enqueue all pending push jobs after successful commit.
        
        Call this AFTER successfully committing the transaction.
        
        Returns:
            int: Total number of jobs enqueued
        """
        from queue_manager import enqueue_sync_job, JOB_PUSH_ITEM, PRIORITY_HIGH
        from reverse_sync_coordinator import should_suppress_push
        
        # Check if push suppression is active (prevents sync loops during reverse sync)
        if should_suppress_push():
            logging.info("⏸️ Push suppression active - skipping marketplace push to prevent sync loop")
            self.pending_jobs = []  # Clear pending jobs
            return 0
        
        total_jobs = 0
        
        for job_tuple in self.pending_jobs:
            # Handle format: (item_id, stores, warehouse_stock_id, sku, is_group_controlled)
            if len(job_tuple) == 5:
                item_id, stores, warehouse_stock_id, sku, is_group_controlled = job_tuple
            elif len(job_tuple) == 4:
                item_id, stores, warehouse_stock_id, sku = job_tuple
                is_group_controlled = False
            elif len(job_tuple) == 3:
                item_id, stores, warehouse_stock_id = job_tuple
                sku = None
                is_group_controlled = False
            else:
                item_id, stores = job_tuple
                warehouse_stock_id = None
                sku = None
                is_group_controlled = False
            
            for store in stores:
                # GO-LIVE GUARD: Defense-in-depth check per store
                allowed, block_reason = guard_store_object(store, f"enqueue_pending_jobs sku={sku}")
                if not allowed:
                    logging.warning(f"[GO_LIVE_GUARD] Skipping enqueue for store {store.name if store else 'Unknown'}: {block_reason}")
                    continue
                
                try:
                    # Build payload - include item_id, warehouse_stock_id, sku, and source
                    # sync_dispatcher requires either item_id OR (warehouse_stock_id + sku)
                    payload = {}
                    if item_id is not None:
                        payload['item_id'] = item_id
                    if warehouse_stock_id is not None:
                        payload['warehouse_stock_id'] = warehouse_stock_id
                    if sku is not None:
                        payload['sku'] = sku
                    
                    # [GROUP_STATE] Set source='group_push' if SKU is group-controlled
                    # This allows the push to pass through [GROUP_BLOCK] checks in sync_dispatcher
                    if is_group_controlled:
                        payload['source'] = 'group_push'
                        logging.info(f"[GROUP_STATE] SKU {sku} is group-controlled, setting source='group_push'")
                    else:
                        payload['source'] = 'warehouse_coordinator'
                    
                    # Ensure we have at least one valid identifier
                    if not payload.get('item_id') and not (payload.get('warehouse_stock_id') and payload.get('sku')):
                        logging.warning(f"Skipping push job with invalid payload for store {store.id}")
                        continue
                    
                    enqueue_sync_job(
                        store_id=store.id,
                        job_type=JOB_PUSH_ITEM,
                        payload=payload,
                        priority=PRIORITY_HIGH
                    )
                    total_jobs += 1
                except Exception as e:
                    logging.error(f"Error enqueueing push job for item_id={item_id}, ws_id={warehouse_stock_id} to store {store.id}: {str(e)}")
                    continue
        
        # Clear pending jobs after enqueueing
        self.pending_jobs = []
        
        logging.info(f"✅ Enqueued {total_jobs} marketplace push jobs")
        return total_jobs
    
    def _prepare_warehouse_push_by_sku(self, sku: str, operation: str = "update") -> Tuple[List[Store], WarehouseStock]:
        """
        Prepare warehouse stock and identify stores for push using SKU directly.
        
        This method works with or without an InventoryItem, supporting warehouse-only SKUs.
        
        GROUP RESOLUTION: If the warehouse stock belongs to a MasterProductGroup,
        this method expands to include ALL stores with listings linked to ANY group member.
        
        Args:
            sku: SKU string to prepare
            operation: Type of operation ("create", "update", "delete")
        
        Returns:
            tuple: (stores_to_push, warehouse_stock) - list of Store objects and WarehouseStock
        """
        from sqlalchemy import or_
        from group_resolution import get_all_group_warehouse_stock_ids, get_primary_warehouse_stock
        
        # Get default warehouse
        default_warehouse = Warehouse.get_default()
        
        # Find warehouse stock for this SKU
        warehouse_stock = WarehouseStock.query.filter_by(
            sku=sku,
            warehouse_id=default_warehouse.id
        ).first()
        
        if not warehouse_stock:
            logging.warning(f"[GROUP_ENFORCE] SKU {sku}: No warehouse stock found, skipping push")
            return [], None
        
        # GROUP RESOLUTION: Expand to all group members if in a MasterProductGroup
        all_warehouse_stock_ids = get_all_group_warehouse_stock_ids(warehouse_stock.id)
        
        if len(all_warehouse_stock_ids) > 1:
            # This SKU is part of a group - use primary warehouse stock as source of truth
            primary = get_primary_warehouse_stock(warehouse_stock.master_product_group_id)
            if primary:
                warehouse_stock = primary
                logging.info(f"[GROUP_RESOLVE] SKU {sku} is in group {warehouse_stock.master_product_group_id}, "
                           f"using primary SKU {primary.sku} for push. Group has {len(all_warehouse_stock_ids)} members.")
        
        # GROUP ENFORCEMENT: Push to ALL linked FBM listings across ALL group members
        # When warehouse quantity changes, ALL group members MUST reflect the same quantity
        # This is MANDATORY for group integrity - store auto_push settings do NOT override this
        
        if operation in ("create", "update"):
            # Get ALL active stores with linked marketplace listings (FBM only - exclude FBA/AFN)
            # EXPANDED: Query across all warehouse_stock_ids in the group
            stores_to_push = db.session.query(Store).join(
                MarketplaceListing, Store.id == MarketplaceListing.store_id
            ).filter(
                Store.is_active == True,
                MarketplaceListing.warehouse_stock_id.in_(all_warehouse_stock_ids),
                MarketplaceListing.is_active == True,
                # Exclude FBA/AFN listings - they are read-only
                or_(
                    MarketplaceListing.amazon_fulfillment_channel.is_(None),
                    MarketplaceListing.amazon_fulfillment_channel == 'MFN',
                    MarketplaceListing.amazon_fulfillment_channel == 'FBM'
                )
            ).distinct().all()
            
            if stores_to_push:
                group_info = f"group {warehouse_stock.master_product_group_id}" if len(all_warehouse_stock_ids) > 1 else f"single SKU {sku}"
                logging.info(f"[GROUP_ENFORCE] {group_info}: Forcing push to {len(stores_to_push)} store(s) for group integrity")
        else:
            stores_to_push = []
        
        return stores_to_push, warehouse_stock


def verify_group_integrity(warehouse_stock_id: int, check_pending_jobs: bool = True) -> dict:
    """
    Verify that all listings linked to a warehouse stock have consistent push quantities.
    
    GROUP RULE: All listings sharing same warehouse_stock_id MUST have been pushed 
    the same quantity (tracked via last_push_quantity).
    
    NOTE: Call this AFTER push jobs have completed. If called immediately after scheduling,
    last_push_quantity may not yet reflect the new values (jobs are async).
    
    Args:
        warehouse_stock_id: ID of the warehouse stock to check
        check_pending_jobs: If True, also check for pending push jobs (default True)
        
    Returns:
        dict with keys:
            - is_consistent: bool - True if all listings' last_push_quantity matches warehouse qty
            - warehouse_qty: int - The warehouse available quantity (source of truth)
            - listing_count: int - Total linked FBM listings
            - mismatched: list - Listings with different last_push_quantity values
            - has_pending_jobs: bool - True if there are pending push jobs for this warehouse
    """
    from sqlalchemy import or_
    from models import SyncJob
    
    result = {
        'is_consistent': True,
        'has_pending_jobs': False,
        'warehouse_qty': 0,
        'listing_count': 0,
        'mismatched': []
    }
    
    try:
        warehouse_stock = WarehouseStock.query.get(warehouse_stock_id)
        if not warehouse_stock:
            logging.warning(f"[GROUP_INTEGRITY] Warehouse stock {warehouse_stock_id} not found")
            return result
        
        result['warehouse_qty'] = warehouse_stock.available_quantity
        
        # Check for pending push jobs if requested
        if check_pending_jobs:
            try:
                # Query pending push jobs and filter by warehouse_stock_id in Python
                # This is database-agnostic (works with both PostgreSQL and SQLite)
                pending_jobs = SyncJob.query.filter(
                    SyncJob.status.in_(['pending', 'in_progress']),
                    SyncJob.job_type == 'push_item'
                ).all()
                
                # Filter for jobs that reference this warehouse_stock_id
                for job in pending_jobs:
                    if job.payload and job.payload.get('warehouse_stock_id') == warehouse_stock_id:
                        result['has_pending_jobs'] = True
                        break
            except Exception as job_err:
                # Fallback: assume no pending jobs if query fails
                logging.debug(f"Could not check pending jobs: {job_err}")
        
        linked_listings = MarketplaceListing.query.filter(
            MarketplaceListing.warehouse_stock_id == warehouse_stock_id,
            MarketplaceListing.is_active == True,
            or_(
                MarketplaceListing.amazon_fulfillment_channel.is_(None),
                MarketplaceListing.amazon_fulfillment_channel == 'MFN',
                MarketplaceListing.amazon_fulfillment_channel == 'FBM'
            )
        ).all()
        
        result['listing_count'] = len(linked_listings)
        
        for listing in linked_listings:
            # Check last_push_quantity - this tracks what was actually pushed to marketplace
            last_pushed = listing.last_push_quantity
            if last_pushed is None or last_pushed != warehouse_stock.available_quantity:
                result['is_consistent'] = False
                result['mismatched'].append({
                    'listing_id': listing.id,
                    'external_sku': listing.external_sku,
                    'platform': listing.store.platform if listing.store else 'unknown',
                    'last_push_qty': last_pushed,
                    'expected_qty': warehouse_stock.available_quantity,
                    'last_push_status': listing.last_push_status
                })
        
        if result['is_consistent']:
            logging.debug(f"[GROUP_INTEGRITY] ✓ SKU {warehouse_stock.sku}: All {result['listing_count']} listings consistent at qty={result['warehouse_qty']}")
        else:
            logging.warning(f"[GROUP_INTEGRITY] ✗ SKU {warehouse_stock.sku}: {len(result['mismatched'])} of {result['listing_count']} listings have mismatched quantities")
            
    except Exception as e:
        logging.error(f"[GROUP_INTEGRITY] Error checking warehouse stock {warehouse_stock_id}: {str(e)}")
        
    return result


def log_group_push_audit(warehouse_stock_id: int, source: str, quantity_pushed: int) -> None:
    """
    Log audit entry when group push is initiated.
    
    Args:
        warehouse_stock_id: ID of warehouse stock being pushed
        source: Source of push (e.g., "warehouse_adjust", "sale_cascade", "quick_scan")
        quantity_pushed: Quantity being pushed to all linked listings
    """
    from sqlalchemy import or_
    
    try:
        warehouse_stock = WarehouseStock.query.get(warehouse_stock_id)
        if not warehouse_stock:
            return
            
        linked_count = MarketplaceListing.query.filter(
            MarketplaceListing.warehouse_stock_id == warehouse_stock_id,
            MarketplaceListing.is_active == True,
            or_(
                MarketplaceListing.amazon_fulfillment_channel.is_(None),
                MarketplaceListing.amazon_fulfillment_channel == 'MFN',
                MarketplaceListing.amazon_fulfillment_channel == 'FBM'
            )
        ).count()
        
        logging.info(
            f"[GROUP_PUSH_AUDIT] source={source} | sku={warehouse_stock.sku} | "
            f"warehouse_stock_id={warehouse_stock_id} | qty={quantity_pushed} | "
            f"linked_listings={linked_count}"
        )
        
    except Exception as e:
        logging.error(f"[GROUP_PUSH_AUDIT] Error logging audit: {str(e)}")
