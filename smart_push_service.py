"""
Smart Push Service - Flexible warehouse-driven inventory sync system
Handles single listings, variations, and unmapped SKUs separately
"""

import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from extensions import db
from models import MarketplaceListing, WarehouseStock, Store, InventoryItem
from ebay_service import eBayAPIService
from amazon_service import AmazonAPIService
from services.go_live_guard import guard_store_object

# Configure logging for debugging
logging.basicConfig(level=logging.DEBUG)

def _classify_listing_safe(listing) -> str:
    """
    Returns one of: 'single', 'variation_parent', 'variation_child', or 'unmapped'.
    Heuristics (non-invasive):
      - If listing.variation_parent_id is not None → 'variation_child'
      - elif getattr(listing, 'variation_children_count', 0) > 0 or getattr(listing, 'variation_theme', None) → 'variation_parent'
      - else → 'single'
    Handle missing attrs with getattr defaults; never raise.
    """
    try:
        if getattr(listing, 'variation_parent_id', None) is not None:
            return 'variation_child'
        if getattr(listing, 'variation_children_count', 0) > 0 or getattr(listing, 'variation_theme', None):
            return 'variation_parent'
        return 'single'
    except Exception:
        return 'unmapped'

class SmartPushService:
    """Intelligent push service that classifies and handles different listing types"""
    
    def __init__(self):
        self.processed_count = 0
        self.success_count = 0
        self.error_count = 0
        
    def classify_listing(self, listing: MarketplaceListing) -> str:
        """Classify listing type based on external_listing_id and known patterns"""
        external_id = listing.external_listing_id
        
        # Already classified
        if listing.listing_type and listing.listing_type != 'single':
            return listing.listing_type
            
        # Check if it has special characters that break XML (block these)
        if any(char in external_id for char in ['&', '<', '>', '"', "'"]):
            return 'invalid_xml'
            
        # Check if it contains variation indicators (needs manual review)
        if any(indicator in external_id for indicator in ['_Un', 'BLMG_Un', '-Un']):
            return 'possible_variation'
            
        # eBay accepts both numeric ItemIDs and SKU values in ReviseInventoryStatus API
        # Treat all valid listings (numeric or SKU-based) as pushable singles
        return 'ebay_single'
        
    def update_listing_classification(self, listing: MarketplaceListing):
        """Update the listing classification in database"""
        classification = self.classify_listing(listing)
        
        # Set listing type based on classification
        if classification == 'ebay_single':
            listing.listing_type = 'single'
            listing.push_state = 'active'
        elif classification == 'possible_variation':
            listing.listing_type = 'variation_child'
            listing.push_state = 'needs_review'  # Needs manual mapping
        elif classification == 'invalid_xml':
            listing.listing_type = 'invalid'
            listing.push_state = 'blocked'
            
        db.session.commit()
        
    def get_pushable_listings(self, store_id: int = None) -> List[MarketplaceListing]:
        """Get listings that can actually be pushed (not blocked/broken)
        
        UNIFIED MODEL: Uses fba_fbm_helpers to check store and listing capabilities.
        FBA listings are read-only (Amazon-controlled), FBM listings can be pushed.
        """
        from fba_fbm_helpers import is_amazon_store, has_fbm_enabled, classify_fulfillment_channel
        
        query = MarketplaceListing.query.filter_by(is_active=True, sync_quantity=True)
        
        if store_id:
            # Check if this store allows pushing (FBM must be enabled for Amazon stores)
            store = Store.query.get(store_id)
            if store and is_amazon_store(store) and not has_fbm_enabled(store):
                logging.info(f"get_pushable_listings: Skipping store {store_id} - FBM sync not enabled")
                return []
            query = query.filter_by(store_id=store_id)
        else:
            # For bulk queries, we'll filter FBA listings at the listing level, not store level
            # This is because a unified Amazon store may have both FBA and FBM listings
            pass
            
        # Only get listings that are pushable and need push
        listings = []
        needs_commit = False
        
        fba_skipped = 0
        for listing in query.all():
            # CRITICAL: Skip FBA listings (they are read-only)
            fulfillment_channel = getattr(listing, 'amazon_fulfillment_channel', None)
            if fulfillment_channel == 'AFN':
                fba_skipped += 1
                continue  # FBA = read-only, never push
            
            # Update classification if not set (but don't commit yet)
            if not listing.listing_type or listing.listing_type == 'single' or listing.listing_type == 'unmapped':
                classification = self.classify_listing(listing)
                
                # Set listing type based on classification (without committing)
                if classification == 'ebay_single':
                    listing.listing_type = 'single'
                    listing.push_state = 'active'
                    needs_commit = True
                elif classification == 'possible_variation':
                    listing.listing_type = 'variation_child'
                    listing.push_state = 'active'
                    needs_commit = True
                elif classification == 'invalid_xml':
                    listing.listing_type = 'invalid'
                    listing.push_state = 'blocked'
                    needs_commit = True
                
            # Only include pushable listings that need push
            if listing.is_pushable and listing.needs_push:
                listings.append(listing)
        
        if fba_skipped > 0:
            logging.info(f"Skipped {fba_skipped} FBA listings (read-only, Amazon-controlled)")
        
        # Batch commit all classification updates
        if needs_commit:
            db.session.commit()
            logging.debug(f"Batch committed classification updates for {len(listings)} listings")
                
        return listings
        
    def push_single_listing(self, listing: MarketplaceListing, store: Store) -> Tuple[bool, Optional[str]]:
        """Push quantity to a single eBay listing"""
        try:
            # Warn about invalid prices but don't block the push (ReviseInventoryStatus is quantity-only)
            if listing.price is not None and listing.price < 0.99:
                logging.warning(f"⚠️ LOW PRICE WARNING: {listing.warehouse_stock.sku} has price £{listing.price:.2f} (below eBay £0.99 minimum). Quantity will still sync. Re-import from eBay to fix price data.")
            
            # ENHANCED PUSH LOGGING: Trace full calculation
            ws = listing.warehouse_stock
            raw_available = ws.available_quantity if ws else 0
            raw_sellable = ws.sellable_quantity if ws else 0
            buffer = listing.quantity_buffer or 0
            max_limit = listing.max_quantity_limit
            warehouse_qty = listing.effective_quantity  # Source of truth
            
            logging.info(f"[PUSH_CALC] SKU={ws.sku if ws else 'UNKNOWN'} | "
                        f"available={raw_available} | sellable={raw_sellable} | "
                        f"buffer={buffer} | max_limit={max_limit or 'None'} | "
                        f"FINAL_PUSH_QTY={warehouse_qty} | NO_SOLD_ADDED=True")
            
            ebay_service = eBayAPIService()
            
            # Initialize with store credentials
            credentials = json.loads(store.api_key)
            ebay_service.auth_token = credentials.get('user_token') or credentials.get('access_token')
            ebay_service.dev_id = credentials.get('dev_id')
            ebay_service.app_id = credentials.get('app_id')
            ebay_service.cert_id = credentials.get('cert_id')
            # BT38 PRODUCTION FIX
            # Never silently default production into sandbox
            ebay_service.use_sandbox = credentials.get('sandbox', False)
            
            # Push warehouse quantity directly - eBay handles sold count automatically
            # ReviseInventoryStatus sets AVAILABLE quantity, eBay adds sold internally
            sku_for_push = listing.external_sku or None
            
            logging.info(f"Pushing {listing.warehouse_stock.sku}: warehouse qty {warehouse_qty} to eBay listing {listing.external_listing_id}")
            
            # Update the listing quantity on eBay (include SKU for multi-variation items)
            success, message = ebay_service.update_listing_quantity(listing.external_listing_id, warehouse_qty, sku=sku_for_push)
            
            if success:
                listing.last_push_at = datetime.utcnow()
                listing.last_push_quantity = warehouse_qty
                listing.last_push_status = 'success'
                listing.last_push_error = None
                listing.consecutive_failures = 0
                listing.push_attempts = 0
                
                logging.info(f"✅ Successfully pushed {listing.warehouse_stock.sku} to {store.name}: qty={warehouse_qty}")
                return True, None
            else:
                # Update failure tracking
                listing.last_push_status = 'error'
                listing.consecutive_failures += 1
                listing.push_attempts += 1
                listing.last_push_error = message
                
                # CRITICAL: Detect missing item specifics errors (e.g., "Language is missing")
                # These are category-specific requirements that MUST be fixed in eBay first
                if "item specific" in message.lower() and "missing" in message.lower():
                    listing.push_state = 'blocked'
                    listing.consecutive_failures = 0  # Reset failures - this is a config issue, not a transient error
                    user_friendly_msg = f"⚠️ BLOCKED: {message}. FIX IN EBAY: Go to eBay Seller Hub → Edit this listing → Add the missing item specific → Save. Then re-import to sync."
                    listing.last_push_error = user_friendly_msg
                    logging.error(f"🚫 BLOCKED listing {listing.external_listing_id}: Missing required item specific. User must fix in eBay first.")
                # Block listing if too many failures (transient errors)
                elif listing.consecutive_failures >= 5:
                    listing.push_state = 'needs_review'
                    logging.warning(f"Blocking {listing.external_listing_id} after {listing.consecutive_failures} failures")
                
                logging.error(f"❌ Failed to push {listing.warehouse_stock.sku} to {store.name}: {message}")
                return False, message
                
        except Exception as e:
            error_msg = f"Push error: {str(e)}"
            listing.last_push_status = 'error'
            listing.consecutive_failures += 1
            listing.push_attempts += 1
            listing.last_push_error = error_msg
            
            # Block listing if too many failures
            if listing.consecutive_failures >= 5:
                listing.push_state = 'needs_review'
                
            logging.error(f"❌ Failed to push {listing.warehouse_stock.sku} to {store.name}: {error_msg}")
            return False, error_msg
        finally:
            db.session.commit()
            
    def push_to_store(self, store: Store) -> Dict:
        """Smart push to a specific store - only processes pushable listings
        
        UNIFIED MODEL: Uses fba_fbm_helpers to check if store allows FBM pushes.
        """
        from fba_fbm_helpers import is_amazon_store, has_fbm_enabled
        
        results = {
            'store_name': store.name,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'skipped_blocked': 0,
            'errors': []
        }
        
        # CRITICAL: Block pushes to Amazon stores without FBM enabled
        if is_amazon_store(store) and not has_fbm_enabled(store):
            logging.warning(f"push_to_store BLOCKED: Store {store.id} ({store.name}) - FBM sync not enabled")
            results['errors'].append("Amazon store FBM sync is disabled - enable it in store settings to push inventory")
            return results
        
        # Get only pushable listings for this store
        pushable_listings = self.get_pushable_listings(store.id)
        
        logging.info(f"Found {len(pushable_listings)} pushable listings for {store.name}")
        
        for listing in pushable_listings:
            results['processed'] += 1
            
            if listing.listing_type == 'single':
                success, error = self.push_single_listing(listing, store)
                if success:
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                    if error:
                        results['errors'].append(f"{listing.warehouse_stock.sku}: {error}")
            else:
                # Skip non-single listings for now (variations need special handling)
                results['skipped_blocked'] += 1
                logging.debug(f"Skipping {listing.listing_type} listing: {listing.external_listing_id}")
                
        return results
        
    def push_specific_sku(self, sku: str, store_name: str = None) -> Dict:
        """Push a specific SKU immediately without waiting for sync cycles"""
        results = {
            'sku': sku,
            'listings_found': 0,
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        # Find warehouse stock
        warehouse_stock = WarehouseStock.query.filter_by(sku=sku).first()
        if not warehouse_stock:
            results['errors'].append(f"SKU {sku} not found in warehouse")
            return results
            
        # Get marketplace listings for this SKU
        query = MarketplaceListing.query.filter_by(warehouse_stock_id=warehouse_stock.id)
        if store_name:
            query = query.join(Store).filter(Store.name == store_name)
            
        listings = query.all()
        results['listings_found'] = len(listings)
        results['blocked_stores'] = []
        
        for listing in listings:
            # GO-LIVE GUARD: Defense-in-depth check per store
            store = listing.store
            allowed, block_reason = guard_store_object(store, f"push_specific_sku sku={sku}")
            if not allowed:
                results['blocked_stores'].append({
                    'store_name': store.name if store else 'Unknown',
                    'reason': block_reason
                })
                results['failed'] += 1
                results['errors'].append(f"Store {store.name if store else 'Unknown'} blocked: {block_reason}")
                continue
            
            # Update classification if needed
            if not listing.listing_type or listing.listing_type == 'single':
                self.update_listing_classification(listing)
                
            if not listing.is_pushable:
                results['errors'].append(f"Listing {listing.external_listing_id} is blocked/needs review")
                continue
            
            # Handle unmapped listings with classification
            effective_type = listing.listing_type
            if listing.listing_type == 'unmapped':
                # Try to classify
                classified = _classify_listing_safe(listing)
                if classified != 'unmapped':
                    logging.warning(f"Listing {sku} type unmapped, classified as {classified}")
                    effective_type = classified
                else:
                    # Last-resort fallback to 'single' if safe
                    platform = listing.store.platform if listing.store else None
                    sibling_count = MarketplaceListing.query.filter_by(
                        warehouse_stock_id=warehouse_stock.id,
                        store_id=listing.store_id
                    ).count()
                    
                    if ('amazon' in (platform or '').lower() and 
                        sibling_count == 1 and 
                        getattr(listing, 'variation_parent_id', None) is None and 
                        getattr(listing, 'variation_theme', None) is None):
                        logging.warning(f"Listing {sku} type unmapped, safe fallback to single ({platform}, 1 listing, no variations)")
                        effective_type = 'single'
                    else:
                        results['errors'].append(f"Listing {sku} type unmapped and cannot be safely classified")
                        continue
                
            if effective_type == 'single':
                store = listing.store
                from fba_fbm_helpers import is_amazon_store, has_fbm_enabled, classify_fulfillment_channel
                
                # Route to appropriate platform service
                if is_amazon_store(store):
                    # UNIFIED MODEL: Check FBM enabled AND listing is not FBA
                    if not has_fbm_enabled(store):
                        results['errors'].append(f"Cannot push - FBM sync not enabled for store (SKU: {sku})")
                        continue
                    
                    # Check if this specific listing is FBA or unclassified (safety block)
                    listing_channel = getattr(listing, 'amazon_fulfillment_channel', None)
                    channel_type = classify_fulfillment_channel(listing_channel)
                    
                    if channel_type == 'FBA':
                        logging.info(f"Blocked push to FBA listing (read-only). SKU={sku}, store={store.name}")
                        results['errors'].append(f"Cannot push to Amazon FBA listing - inventory is Amazon-controlled (SKU: {sku})")
                        continue
                    
                    # SAFETY: Block unknown channels until explicitly classified as FBM
                    if channel_type is None:
                        logging.warning(f"Blocked push to unclassified Amazon listing. SKU={sku}, channel={listing_channel}")
                        results['errors'].append(f"Cannot push - listing has unknown fulfillment channel (SKU: {sku}). Sync first to classify.")
                        continue
                    
                    # Push to Amazon FBM (explicitly classified) - warehouse controls inventory
                    inventory_item = InventoryItem.query.filter_by(sku=sku).first()
                    
                    if not inventory_item:
                        results['errors'].append(f"No inventory item found for {sku}")
                        continue
                    
                    amazon_service = AmazonAPIService()
                    success, error = amazon_service.sync_inventory_to_amazon(store, inventory_item)
                    
                    if success:
                        # Update listing tracking (same as eBay)
                        listing.last_push_at = datetime.utcnow()
                        listing.last_push_quantity = listing.effective_quantity
                        listing.last_push_status = 'success'
                        listing.last_push_error = None
                        listing.consecutive_failures = 0
                        listing.push_attempts = 0
                        db.session.commit()
                        results['successful'] += 1
                    else:
                        # Update failure tracking
                        listing.last_push_status = 'error'
                        listing.consecutive_failures += 1
                        listing.push_attempts += 1
                        listing.last_push_error = error
                        if listing.consecutive_failures >= 5:
                            listing.push_state = 'needs_review'
                        db.session.commit()
                        results['failed'] += 1
                        if error:
                            results['errors'].append(f"{sku}: {error}")
                elif store.platform == 'eBay':
                    # Push to eBay
                    success, error = self.push_single_listing(listing, store)
                    if success:
                        results['successful'] += 1
                    else:
                        results['failed'] += 1
                        if error:
                            results['errors'].append(f"{listing.external_listing_id}: {error}")
                else:
                    results['errors'].append(f"Platform {store.platform} not supported")
            else:
                results['errors'].append(f"Listing {listing.external_listing_id} type {effective_type} not supported yet")
                
        return results

# Global instance
smart_push_service = SmartPushService()