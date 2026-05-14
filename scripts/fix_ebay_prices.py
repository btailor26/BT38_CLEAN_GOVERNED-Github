"""
eBay Price Remediation Script
Fixes eBay listings with prices below marketplace minimum (£0.99)
"""
import logging
import csv
import time
from datetime import datetime
from typing import List, Dict, Tuple
from app import db
from models import MarketplaceListing, Store, WarehouseStock, SyncLog
from ebay_service import eBayAPIService

logger = logging.getLogger(__name__)

def get_affected_listings(min_price: float, store_name: str | None = None) -> List[MarketplaceListing]:
    """
    Find eBay listings with prices below minimum
    
    Args:
        min_price: Minimum price threshold (e.g., 0.99)
        store_name: Optional store name filter
        
    Returns:
        List of affected MarketplaceListing objects
    """
    query = db.session.query(MarketplaceListing).join(
        Store
    ).filter(
        Store.platform == 'eBay',
        MarketplaceListing.is_active == True,
        MarketplaceListing.price < min_price
    )
    
    if store_name:
        query = query.filter(Store.name == store_name)
    
    listings = query.all()
    logger.info(f"Found {len(listings)} eBay listings with price < £{min_price:.2f}")
    
    return listings

def fix_ebay_prices(
    min_price: float = 0.99,
    dry_run: bool = True,
    apply: bool = False,
    store_name: str | None = None,
    batch_size: int = 20
) -> bool:
    """
    Fix eBay listings with prices below minimum
    
    Args:
        min_price: Minimum price to enforce (default: 0.99)
        dry_run: If True, only report changes without applying
        apply: If True, actually apply the changes
        store_name: Optional store name filter
        batch_size: Number of items to process per batch
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate arguments
        if not dry_run and not apply:
            logger.error("Must specify either --dry-run or --apply")
            return False
        
        if dry_run and apply:
            logger.warning("Both --dry-run and --apply specified, defaulting to dry-run")
            apply = False
        
        # Get affected listings
        affected_listings = get_affected_listings(min_price, store_name)
        
        if not affected_listings:
            logger.info("✅ No eBay listings found with prices below minimum")
            return True
        
        # Prepare results tracking
        results: List[Dict] = []
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        # Initialize eBay service
        ebay_service = eBayAPIService()
        
        # Process in batches
        for i in range(0, len(affected_listings), batch_size):
            batch = affected_listings[i:i+batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(affected_listings)-1)//batch_size + 1}")
            
            for listing in batch:
                result: Dict = {}  # Initialize to prevent unbound variable
                try:
                    # Get store and warehouse info
                    store = listing.store
                    warehouse_stock = listing.warehouse_stock
                    old_price = listing.price or 0.0
                    
                    # Determine new price
                    # Business rule: Use the specified minimum price or keep current if above
                    new_price = max(min_price, old_price) if old_price > 0 else min_price
                    
                    # Build result entry
                    result = {
                        'itemId': listing.external_listing_id,
                        'sku': warehouse_stock.sku if warehouse_stock else 'N/A',
                        'store': store.name,
                        'oldPrice': f"{old_price:.2f}",
                        'newPrice': f"{new_price:.2f}",
                        'changedAtUTC': datetime.utcnow().isoformat(),
                        'status': 'pending'
                    }
                    
                    # Dry run - just report
                    if dry_run:
                        result['status'] = 'dry-run'
                        logger.info(f"[DRY-RUN] Would update {listing.external_listing_id} (SKU: {result['sku']}): £{old_price:.2f} → £{new_price:.2f}")
                        results.append(result)
                        skipped_count += 1
                        continue
                    
                    # Apply mode - actually update via eBay API
                    if apply:
                        logger.info(f"Updating {listing.external_listing_id} (SKU: {result['sku']}): £{old_price:.2f} → £{new_price:.2f}")
                        
                        # Call eBay API to update price
                        success, message = ebay_service.update_listing_price(
                            store=store,
                            item_id=listing.external_listing_id,
                            new_price=new_price,
                            sku=listing.external_sku
                        )
                        
                        if success:
                            # Update local database
                            listing.price = new_price
                            listing.push_state = 'active'  # Reactivate for push
                            listing.consecutive_failures = 0
                            listing.last_push_error = None
                            
                            result['status'] = 'success'
                            success_count += 1
                            
                            # Log to SyncLog
                            sync_log = SyncLog(  # type: ignore[call-arg]
                                store_id=store.id,
                                status='completed',
                                message=f"Price remediation: {listing.external_listing_id} updated from £{old_price:.2f} to £{new_price:.2f}",
                                items_synced=1
                            )
                            db.session.add(sync_log)
                            
                            logger.info(f"✅ Successfully updated {listing.external_listing_id}")
                        else:
                            result['status'] = f'error: {message}'
                            result['errorMessage'] = message
                            error_count += 1
                            logger.error(f"❌ Failed to update {listing.external_listing_id}: {message}")
                        
                        results.append(result)
                        
                        # Rate limiting - wait between API calls
                        time.sleep(0.5)
                
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error processing listing {listing.external_listing_id}: {error_msg}")
                    result['status'] = f'error: {error_msg}'
                    result['errorMessage'] = error_msg
                    results.append(result)
                    error_count += 1
            
            # Commit batch changes
            if apply:
                try:
                    db.session.commit()
                    logger.info(f"Committed batch {i//batch_size + 1}")
                except Exception as e:
                    logger.error(f"Error committing batch: {str(e)}")
                    db.session.rollback()
        
        # Generate CSV report
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        mode = 'dry_run' if dry_run else 'applied'
        csv_filename = f"reports/ebay_price_fix_{mode}_{timestamp}.csv"
        
        with open(csv_filename, 'w', newline='') as csvfile:
            if results:
                fieldnames = ['itemId', 'sku', 'store', 'oldPrice', 'newPrice', 'changedAtUTC', 'status']
                if any('errorMessage' in r for r in results):
                    fieldnames.append('errorMessage')
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(results)
        
        logger.info(f"📄 CSV report written to: {csv_filename}")
        
        # Print summary
        logger.info("=" * 80)
        logger.info(f"eBay Price Remediation Summary ({mode.upper()})")
        logger.info("=" * 80)
        logger.info(f"Total listings found: {len(affected_listings)}")
        logger.info(f"Successfully updated: {success_count}")
        logger.info(f"Errors: {error_count}")
        logger.info(f"Skipped (dry-run): {skipped_count}")
        logger.info(f"CSV report: {csv_filename}")
        logger.info("=" * 80)
        
        if apply and success_count > 0:
            logger.info(f"✅ Price remediation completed: {success_count}/{len(affected_listings)} listings updated")
            logger.info("Next steps:")
            logger.info("1. Wait for next sync cycle (30 seconds)")
            logger.info("2. Verify listings transition from 'blocked' to 'pushable'")
            logger.info("3. Check push status in dashboard or logs")
        
        return error_count == 0
        
    except Exception as e:
        logger.error(f"Fatal error in fix_ebay_prices: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
