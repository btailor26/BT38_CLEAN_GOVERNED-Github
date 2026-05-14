"""
Reverse Sync Coordinator

Handles bidirectional syncing: marketplace stock changes → warehouse stock updates.
Prevents sync loops by suppressing automatic warehouse→marketplace pushes for marketplace-originated changes.
"""

import logging
from typing import Optional, Tuple
from datetime import datetime
from flask import g
from sqlalchemy import select
from app import db
from models import MarketplaceListing, WarehouseStock, Store, StockLedgerEntry, Warehouse


class ReverseSyncCoordinator:
    """
    Coordinates marketplace → warehouse stock syncing.
    
    Usage:
        coordinator = ReverseSyncCoordinator()
        coordinator.sync_quantity_from_marketplace(
            marketplace_listing=listing,
            current_marketplace_qty=15,
            store=store
        )
    """
    
    def __init__(self):
        """Initialize the coordinator"""
        self.changes_made = 0
        
    def sync_quantity_from_marketplace(
        self,
        marketplace_listing: MarketplaceListing,
        current_marketplace_qty: int,
        store: Store
    ) -> bool:
        """
        DISABLED: Reverse sync is permanently disabled.
        
        Warehouse is the ONLY source of truth. Marketplace quantities are READ-ONLY.
        Until sales ingestion is implemented, we cannot safely update warehouse from marketplace.
        
        Previous behavior caused 14→22 inflation bug:
        - eBay reports Quantity = Available + Sold = 22
        - Reverse sync would update warehouse to 22
        - Push would then send 22 to eBay (should be 14)
        
        Args:
            marketplace_listing: MarketplaceListing record
            current_marketplace_qty: Current quantity on marketplace (IGNORED)
            store: Store object with reverse_sync settings
        
        Returns:
            bool: Always returns False (no updates made)
        """
        # HARD DISABLE: Never update warehouse from marketplace
        # This is a critical safety measure to prevent quantity inflation bugs
        logging.debug(f"[REVERSE_SYNC_DISABLED] Skipping marketplace→warehouse sync for {store.name} - warehouse is authoritative")
        return False
        
        # ORIGINAL CODE DISABLED BELOW - DO NOT ENABLE WITHOUT SALES INGESTION
        # Check if reverse sync is enabled for this store
        if not store.reverse_sync_enabled:
            logging.debug(f"Reverse sync disabled for {store.name}, skipping")
            return False
        
        # Get the warehouse stock
        warehouse_stock = marketplace_listing.warehouse_stock
        if not warehouse_stock:
            logging.warning(f"No warehouse stock found for listing {marketplace_listing.id}, cannot sync")
            return False
        
        # Update tracking fields on marketplace listing
        prev_marketplace_qty = marketplace_listing.last_marketplace_qty
        marketplace_listing.last_marketplace_qty = current_marketplace_qty
        marketplace_listing.last_synced_at = datetime.utcnow()
        
        # Determine if quantity has changed
        if prev_marketplace_qty is None:
            # First time seeing this quantity - sync it
            logging.info(f"First sync for {marketplace_listing.external_listing_id}, initializing with {current_marketplace_qty}")
            quantity_changed = True
        else:
            quantity_changed = prev_marketplace_qty != current_marketplace_qty
        
        if not quantity_changed:
            # No change detected
            return False
        
        # Quantity has changed - apply sync policy
        # SAFETY: Default to warehouse authority if policy is not explicitly set
        sync_policy = store.sync_priority_policy or 'warehouse'
        
        if sync_policy == 'marketplace':
            # Marketplace is authoritative - always update warehouse
            return self._update_warehouse_from_marketplace(
                warehouse_stock=warehouse_stock,
                new_quantity=current_marketplace_qty,
                store=store,
                marketplace_listing=marketplace_listing,
                reason=f"Marketplace sync from {store.name} (marketplace priority)"
            )
        elif sync_policy == 'warehouse':
            # Warehouse is authoritative - don't update from marketplace
            logging.debug(f"Warehouse priority policy - ignoring marketplace change for {warehouse_stock.sku}")
            return False
        elif sync_policy == 'last_write_wins':
            # Check timestamps to determine which is newer
            if warehouse_stock.updated_at and marketplace_listing.last_synced_at:
                if marketplace_listing.last_synced_at > warehouse_stock.updated_at:
                    # Marketplace update is newer
                    return self._update_warehouse_from_marketplace(
                        warehouse_stock=warehouse_stock,
                        new_quantity=current_marketplace_qty,
                        store=store,
                        marketplace_listing=marketplace_listing,
                        reason=f"Marketplace sync from {store.name} (last write wins)"
                    )
                else:
                    logging.debug(f"Warehouse update is newer for {warehouse_stock.sku}, ignoring marketplace change")
                    return False
            else:
                # Missing timestamps, default to marketplace
                return self._update_warehouse_from_marketplace(
                    warehouse_stock=warehouse_stock,
                    new_quantity=current_marketplace_qty,
                    store=store,
                    marketplace_listing=marketplace_listing,
                    reason=f"Marketplace sync from {store.name} (default to marketplace)"
                )
        
        return False
    
    def _update_warehouse_from_marketplace(
        self,
        warehouse_stock: WarehouseStock,
        new_quantity: int,
        store: Store,
        marketplace_listing: MarketplaceListing,
        reason: str
    ) -> bool:
        """
        Update warehouse stock from marketplace quantity with row-level locking.
        
        Args:
            warehouse_stock: WarehouseStock to update
            new_quantity: New quantity from marketplace
            store: Store object
            marketplace_listing: MarketplaceListing record
            reason: Human-readable reason for the change
        
        Returns:
            bool: True if update was successful
        """
        try:
            # CRITICAL: Acquire row-level lock to prevent concurrent modifications
            # This prevents race conditions during simultaneous marketplace sales
            locked_stock = db.session.execute(
                select(WarehouseStock)
                .filter_by(id=warehouse_stock.id)
                .with_for_update()  # SELECT FOR UPDATE - blocks other transactions
            ).scalar_one_or_none()
            
            if not locked_stock:
                logging.error(f"Failed to acquire lock on warehouse stock {warehouse_stock.id}")
                return False
            
            # Capture before state for ledger
            before_qty = locked_stock.available_quantity
            
            # Set suppression flag to prevent push loop
            self._set_push_suppression(True)
            
            # Update warehouse quantity with optimistic locking
            locked_stock.available_quantity = new_quantity
            locked_stock.stock_version += 1  # Increment version for optimistic locking
            locked_stock.last_sync_at = datetime.utcnow()
            locked_stock.updated_at = datetime.utcnow()
            
            # Create audit trail entry
            ledger_entry = StockLedgerEntry(
                warehouse_stock_id=locked_stock.id,
                transaction_type='marketplace_sync',
                adjustment_type='set',
                available_quantity_before=before_qty,
                available_quantity_after=new_quantity,
                reserved_quantity_before=locked_stock.reserved_quantity,
                reserved_quantity_after=locked_stock.reserved_quantity,
                allocated_quantity_before=locked_stock.allocated_quantity,
                allocated_quantity_after=locked_stock.allocated_quantity,
                on_order_quantity_before=locked_stock.on_order_quantity,
                on_order_quantity_after=locked_stock.on_order_quantity,
                pending_receipt_qty_before=locked_stock.pending_receipt_qty,
                pending_receipt_qty_after=locked_stock.pending_receipt_qty,
                quarantined_quantity_before=locked_stock.quarantined_quantity,
                quarantined_quantity_after=locked_stock.quarantined_quantity,
                reason=reason,
                reference_id=str(marketplace_listing.id),
                reference_type='marketplace_listing',
                created_by='system',
                source_system='marketplace',
                update_source='marketplace_sync',
                notes=f"Synced from {store.platform} listing {marketplace_listing.external_listing_id}"
            )
            db.session.add(ledger_entry)
            
            logging.info(f"✅ Reverse sync: Updated warehouse stock for {locked_stock.sku} from {before_qty} → {new_quantity} (from {store.name}, version {locked_stock.stock_version})")
            self.changes_made += 1
            
            return True
            
        except Exception as e:
            logging.error(f"Error updating warehouse from marketplace: {str(e)}")
            return False
        finally:
            # Always clear suppression flag after update
            self._set_push_suppression(False)
    
    def _set_push_suppression(self, suppress: bool):
        """
        Set or clear the push suppression flag to prevent sync loops.
        
        Uses Flask's `g` object for request-scoped storage when available,
        falls back to thread-local storage for background workers.
        
        Args:
            suppress: True to suppress pushes, False to allow them
        """
        try:
            from flask import has_request_context
            
            if has_request_context():
                # In request context - use Flask g object
                if not hasattr(g, '_suppress_marketplace_push'):
                    g._suppress_marketplace_push = False
                g._suppress_marketplace_push = suppress
                logging.debug(f"Push suppression (request context): {suppress}")
            else:
                # Background worker - use thread-local storage
                import threading
                if not hasattr(threading.current_thread(), '_suppress_marketplace_push'):
                    threading.current_thread()._suppress_marketplace_push = False
                threading.current_thread()._suppress_marketplace_push = suppress
                logging.debug(f"Push suppression (thread-local): {suppress}")
        except Exception as e:
            logging.warning(f"Could not set push suppression: {str(e)}")
    
    @staticmethod
    def is_push_suppressed() -> bool:
        """
        Check if marketplace pushes are currently suppressed.
        
        Checks both request context and thread-local storage.
        
        Returns:
            bool: True if pushes should be suppressed
        """
        try:
            from flask import has_request_context
            
            if has_request_context():
                # Check Flask g object
                return getattr(g, '_suppress_marketplace_push', False)
            else:
                # Check thread-local storage
                import threading
                return getattr(threading.current_thread(), '_suppress_marketplace_push', False)
        except Exception:
            return False


# Helper function for WarehousePushCoordinator to check suppression
def should_suppress_push() -> bool:
    """
    Check if automatic pushes should be suppressed (e.g., during reverse sync).
    
    Returns:
        bool: True if pushes should be suppressed
    """
    return ReverseSyncCoordinator.is_push_suppressed()
