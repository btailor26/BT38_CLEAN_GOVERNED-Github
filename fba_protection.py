"""
FBA Protection Utilities

Central module for protecting FBA inventory from accidental push operations.
FBA inventory is read-only - Amazon controls the stock levels.

All push operations must go through these guards.
"""

import logging
from typing import Tuple, List, Set
from app import db
from sqlalchemy import select

logger = logging.getLogger(__name__)


def is_fba_protected(warehouse_stock_id: int) -> Tuple[bool, str]:
    """
    Check if a warehouse stock item is linked to an FBA store and should be protected.
    
    FBA inventory is managed by Amazon - we cannot push stock to FBA stores.
    
    Args:
        warehouse_stock_id: The WarehouseStock.id to check
        
    Returns:
        (is_protected, reason) - True if push should be blocked, with reason
    """
    from models import MarketplaceListing, Store
    
    fba_listing = db.session.query(MarketplaceListing).join(
        Store, MarketplaceListing.store_id == Store.id
    ).filter(
        MarketplaceListing.warehouse_stock_id == warehouse_stock_id,
        Store.platform == 'AmazonFBA'
    ).first()
    
    if fba_listing:
        return True, "FBA listings are read-only; stock is managed by Amazon."
    
    return False, ""


def get_fba_linked_warehouse_ids() -> Set[int]:
    """
    Get all WarehouseStock IDs that are linked to Amazon FBA stores.
    
    These items should be excluded from the Warehouse Stock page and
    all warehouse-level push operations.
    
    Returns:
        Set of WarehouseStock IDs linked to FBA stores
    """
    from models import MarketplaceListing, Store
    
    fba_linked = db.session.query(MarketplaceListing.warehouse_stock_id).join(
        Store, MarketplaceListing.store_id == Store.id
    ).filter(
        Store.platform == 'AmazonFBA',
        MarketplaceListing.warehouse_stock_id.isnot(None)
    ).distinct().all()
    
    return {row[0] for row in fba_linked}


def filter_fba_protected_ids(warehouse_stock_ids: List[int]) -> Tuple[List[int], List[int]]:
    """
    Filter a list of warehouse stock IDs, separating FBA-protected from pushable.
    
    Args:
        warehouse_stock_ids: List of WarehouseStock IDs to check
        
    Returns:
        (pushable_ids, blocked_ids) - IDs that can be pushed vs those blocked
    """
    fba_linked = get_fba_linked_warehouse_ids()
    
    pushable = []
    blocked = []
    
    for ws_id in warehouse_stock_ids:
        if ws_id in fba_linked:
            blocked.append(ws_id)
        else:
            pushable.append(ws_id)
    
    if blocked:
        logger.info(f"FBA Protection: Blocked {len(blocked)} FBA-linked items from push: {blocked}")
    
    return pushable, blocked


def validate_push_operation(warehouse_stock_ids: List[int], 
                           allow_partial: bool = True) -> Tuple[bool, str, List[int]]:
    """
    Validate a push operation, blocking any FBA-linked items.
    
    Args:
        warehouse_stock_ids: List of WarehouseStock IDs to push
        allow_partial: If True, allow pushing non-FBA items even if some are blocked
        
    Returns:
        (success, message, pushable_ids)
    """
    from models import WarehouseStock
    
    if not warehouse_stock_ids:
        return False, "No items to push", []
    
    pushable, blocked = filter_fba_protected_ids(warehouse_stock_ids)
    
    if blocked:
        blocked_skus = db.session.query(WarehouseStock.sku).filter(
            WarehouseStock.id.in_(blocked)
        ).all()
        blocked_sku_list = [s[0] for s in blocked_skus]
        
        if not allow_partial:
            return False, f"FBA listings are read-only; stock is managed by Amazon. Blocked SKUs: {blocked_sku_list}", []
        
        if not pushable:
            return False, f"All selected items are FBA-linked and read-only. Blocked SKUs: {blocked_sku_list}", []
        
        logger.warning(f"Partial push: Blocked {len(blocked)} FBA items, proceeding with {len(pushable)} pushable items")
    
    return True, f"Validated {len(pushable)} items for push", pushable


def get_warehouse_stock_query_excluding_fba():
    """
    Get a base query for WarehouseStock that excludes FBA-linked items.
    
    Use this for the Warehouse Stock page and any FBM-only operations.
    
    Returns:
        SQLAlchemy query for non-FBA warehouse stock
    """
    from models import WarehouseStock, MarketplaceListing, Store
    
    fba_subquery = db.session.query(MarketplaceListing.warehouse_stock_id).join(
        Store, MarketplaceListing.store_id == Store.id
    ).filter(
        Store.platform == 'AmazonFBA',
        MarketplaceListing.warehouse_stock_id.isnot(None)
    ).distinct().subquery()
    
    return db.session.query(WarehouseStock).filter(
        ~WarehouseStock.id.in_(select(fba_subquery.c.warehouse_stock_id))
    )


def get_fba_warehouse_stock_query():
    """
    Get a query for WarehouseStock items that ARE linked to FBA stores.
    
    Use this for the Amazon FBA Stock page (read-only view).
    
    Returns:
        SQLAlchemy query for FBA-linked warehouse stock
    """
    from models import WarehouseStock, MarketplaceListing, Store
    
    fba_subquery = db.session.query(MarketplaceListing.warehouse_stock_id).join(
        Store, MarketplaceListing.store_id == Store.id
    ).filter(
        Store.platform == 'AmazonFBA',
        MarketplaceListing.warehouse_stock_id.isnot(None)
    ).distinct().subquery()
    
    return db.session.query(WarehouseStock).filter(
        WarehouseStock.id.in_(select(fba_subquery.c.warehouse_stock_id))
    )


def log_fba_push_attempt(warehouse_stock_ids: List[int], source: str):
    """
    Log an attempted push to FBA-linked items for monitoring.
    
    Args:
        warehouse_stock_ids: IDs that were blocked
        source: Where the push attempt came from (e.g., 'warehouse_page', 'api')
    """
    from models import WarehouseStock, SystemLog
    
    if not warehouse_stock_ids:
        return
    
    skus = db.session.query(WarehouseStock.sku).filter(
        WarehouseStock.id.in_(warehouse_stock_ids)
    ).all()
    sku_list = [s[0] for s in skus]
    
    log_entry = SystemLog(
        log_type='fba_push_blocked',
        route_name=source,
        success=False,
        error_reason=f"Blocked FBA push attempt for SKUs: {sku_list}"
    )
    db.session.add(log_entry)
    
    try:
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to log FBA push attempt: {e}")
        db.session.rollback()
    
    logger.warning(f"FBA Push Blocked [{source}]: Attempted push for {len(warehouse_stock_ids)} FBA-linked items: {sku_list}")
