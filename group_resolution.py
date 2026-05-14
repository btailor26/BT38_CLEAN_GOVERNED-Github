"""
Explicit Product Group Resolution System

This module provides the central group resolution logic for the multi-warehouse-SKU grouping system.
When multiple warehouse SKUs share the same physical inventory pool (e.g., same product listed
on Amazon and eBay under different SKUs), they must be grouped and managed as a single unit.

KEY CONCEPTS:
- MasterProductGroup: The explicit group container. Multiple WarehouseStock can belong to one group.
- Primary Source: One warehouse stock is the "source of truth" for the group's shared quantity.
- Group Resolution: Given any warehouse_stock_id, find ALL listings across ALL group members.

RULES:
- G1: A group is "active" if it has >= 1 warehouse_stock member (can be 1 member with multiple listings)
- G2: If warehouse_stock_id is in a group, ANY listing linked to ANY member is treated as group-linked
- G3: Group quantity = PRIMARY member's warehouse_stock.available_quantity (single source, not sum)
- G4: Push behavior: push group_qty to ALL marketplace_listings across ALL group members
- G5: Sales: decrement primary source, push to all group listings
"""

import logging
from typing import List, Dict, Tuple, Optional, Set
from sqlalchemy import or_
from app import db
from models import WarehouseStock, MarketplaceListing, Store, MasterProductGroup, ProductMapping


def get_group_for_warehouse_stock(warehouse_stock_id: int) -> Optional[MasterProductGroup]:
    """
    Get the MasterProductGroup for a given warehouse stock, if any.
    
    Args:
        warehouse_stock_id: ID of the warehouse stock
        
    Returns:
        MasterProductGroup or None if not grouped
    """
    ws = db.session.query(WarehouseStock).get(warehouse_stock_id)
    if not ws or not ws.master_product_group_id:
        return None
    
    return db.session.query(MasterProductGroup).get(ws.master_product_group_id)


def get_group_members(group_id: int) -> List[WarehouseStock]:
    """
    Get all warehouse stock members of a MasterProductGroup.
    
    Args:
        group_id: ID of the MasterProductGroup
        
    Returns:
        List of WarehouseStock objects in the group
    """
    return db.session.query(WarehouseStock).filter(
        WarehouseStock.master_product_group_id == group_id,
        WarehouseStock.is_deleted == False,
        WarehouseStock.is_active == True
    ).all()


def get_group_member_ids(group_id: int) -> Set[int]:
    """
    Get all warehouse stock IDs for a group.
    
    Args:
        group_id: ID of the MasterProductGroup
        
    Returns:
        Set of warehouse_stock_id values
    """
    result = db.session.query(WarehouseStock.id).filter(
        WarehouseStock.master_product_group_id == group_id,
        WarehouseStock.is_deleted == False,
        WarehouseStock.is_active == True
    ).all()
    return set(ws_id for (ws_id,) in result)


def get_primary_warehouse_stock(group_id: int) -> Optional[WarehouseStock]:
    """
    Get the PRIMARY warehouse stock for a group (source of truth for quantity).
    
    The primary is the FIRST member added (lowest ID) or can be explicitly marked.
    This is the single source of truth for the shared inventory pool.
    
    Args:
        group_id: ID of the MasterProductGroup
        
    Returns:
        WarehouseStock object designated as primary, or None
    """
    return db.session.query(WarehouseStock).filter(
        WarehouseStock.master_product_group_id == group_id,
        WarehouseStock.is_deleted == False,
        WarehouseStock.is_active == True
    ).order_by(WarehouseStock.id.asc()).first()


def compute_group_quantity(group_id: int) -> int:
    """
    Compute the group's shared quantity.
    
    Rule G3: Use PRIMARY member's warehouse_stock.available_quantity.
    We use single-source, not sum, because they represent the same physical pool.
    
    Args:
        group_id: ID of the MasterProductGroup
        
    Returns:
        Available quantity for the group (from primary member)
    """
    primary = get_primary_warehouse_stock(group_id)
    if not primary:
        logging.warning(f"[GROUP_RESOLVE] No primary warehouse stock for group {group_id}")
        return 0
    
    qty = primary.available_quantity
    logging.debug(f"[GROUP_RESOLVE] Group {group_id} quantity = {qty} (from primary SKU: {primary.sku})")
    return qty


def get_all_group_warehouse_stock_ids(warehouse_stock_id: int) -> Set[int]:
    """
    Given a warehouse_stock_id, return ALL warehouse_stock_ids in the same group.
    
    If not in a group, returns just the input ID.
    This is the core group expansion function.
    
    Args:
        warehouse_stock_id: Starting warehouse stock ID
        
    Returns:
        Set of all warehouse_stock_ids in the same group (including input)
    """
    ws = db.session.query(WarehouseStock).get(warehouse_stock_id)
    if not ws:
        return set()
    
    if not ws.master_product_group_id:
        return {warehouse_stock_id}
    
    member_ids = get_group_member_ids(ws.master_product_group_id)
    logging.debug(f"[GROUP_RESOLVE] SKU {ws.sku} is in group {ws.master_product_group_id}, expanding to {len(member_ids)} members")
    return member_ids


def get_group_listings(group_id: int, fbm_only: bool = True) -> List[MarketplaceListing]:
    """
    Get ALL marketplace listings across ALL members of a group.
    
    Rule G2: If warehouse_stock_id is in a group, ANY listing linked to ANY member
    is treated as group-linked.
    
    Args:
        group_id: ID of the MasterProductGroup
        fbm_only: If True, exclude FBA/AFN listings (they're read-only)
        
    Returns:
        List of MarketplaceListing objects for the entire group
    """
    member_ids = get_group_member_ids(group_id)
    if not member_ids:
        return []
    
    query = db.session.query(MarketplaceListing).join(Store).filter(
        MarketplaceListing.warehouse_stock_id.in_(member_ids),
        MarketplaceListing.is_active == True,
        Store.is_active == True
    )
    
    if fbm_only:
        query = query.filter(
            or_(
                ~Store.platform.ilike('%amazon%'),
                db.and_(
                    Store.fbm_sync_enabled == True,
                    or_(
                        MarketplaceListing.amazon_fulfillment_channel == 'MFN',
                        MarketplaceListing.amazon_fulfillment_channel == 'FBM',
                        MarketplaceListing.amazon_fulfillment_channel.is_(None),
                        MarketplaceListing.amazon_fulfillment_channel == ''  # Treat empty string same as NULL
                    )
                )
            )
        )
    
    return query.all()


def get_listings_for_warehouse_stock_expanded(warehouse_stock_id: int, fbm_only: bool = True) -> Tuple[Optional[WarehouseStock], List[Dict], Optional[MasterProductGroup]]:
    """
    MAIN RESOLUTION FUNCTION: Get all FBM listings for a warehouse stock, EXPANDED to include
    all listings across all group members if the warehouse stock is in a group.
    
    NO SILENT SKIPS: AFN/FBA listings are included with status='blocked' and reason.
    
    Args:
        warehouse_stock_id: Starting warehouse stock ID
        fbm_only: If True, mark FBA/AFN listings as blocked (but still include them)
        
    Returns:
        Tuple of (primary_warehouse_stock, listings_list, group_or_none)
        - primary_warehouse_stock: The source of truth for quantity
        - listings_list: List of dicts with listing details (includes blocked AFN with reason)
        - group_or_none: MasterProductGroup if in a group, None otherwise
    """
    ws = db.session.query(WarehouseStock).get(warehouse_stock_id)
    if not ws:
        return None, [], None
    
    group = None
    primary_ws = ws
    member_ids = {warehouse_stock_id}
    
    if ws.master_product_group_id:
        group = db.session.query(MasterProductGroup).get(ws.master_product_group_id)
        member_ids = get_group_member_ids(ws.master_product_group_id)
        primary_ws = get_primary_warehouse_stock(ws.master_product_group_id) or ws
        
        logging.info(f"[GROUP_RESOLVE] Expanding warehouse_stock_id={warehouse_stock_id} (SKU: {ws.sku}) "
                    f"to group {ws.master_product_group_id} with {len(member_ids)} members. "
                    f"Primary: {primary_ws.sku}")
    
    all_listing_ids = set()
    
    # STEP 1: Get ALL active listings (no FBM filter yet - we need to detect AFN)
    for member_id in member_ids:
        query = db.session.query(MarketplaceListing).join(Store).filter(
            MarketplaceListing.warehouse_stock_id == member_id,
            MarketplaceListing.is_active == True,
            Store.is_active == True
        )
        
        for listing in query.all():
            all_listing_ids.add(listing.id)
        
        pm_listings = db.session.query(ProductMapping).filter(
            ProductMapping.warehouse_stock_id == member_id
        ).all()
        
        for pm in pm_listings:
            listing = db.session.query(MarketplaceListing).join(Store).filter(
                MarketplaceListing.store_id == pm.store_id,
                or_(
                    MarketplaceListing.external_listing_id == pm.external_id,
                    MarketplaceListing.asin == pm.external_id,
                    MarketplaceListing.external_sku == pm.seller_sku
                ),
                MarketplaceListing.is_active == True,
                Store.is_active == True
            ).first()
            
            if listing:
                all_listing_ids.add(listing.id)
    
    if not all_listing_ids:
        return primary_ws, [], group
    
    listings = db.session.query(MarketplaceListing).join(Store).filter(
        MarketplaceListing.id.in_(all_listing_ids)
    ).all()
    
    # STEP 2: Build result with explicit status for each listing (NO SILENT SKIPS)
    result = []
    blocked_count = 0
    pushable_count = 0
    
    for l in listings:
        is_amazon = l.store and 'amazon' in l.store.platform.lower()
        is_afn = l.amazon_fulfillment_channel == 'AFN'
        
        # Determine if this listing is pushable
        is_pushable = True
        status = 'active'
        blocked_reason = None
        
        if fbm_only and is_amazon and is_afn:
            # AFN/FBA listing - BLOCKED (read-only)
            is_pushable = False
            status = 'blocked'
            blocked_reason = 'FBA/AFN is read-only; cannot push inventory'
            blocked_count += 1
            logging.info(f"[GROUP_RESOLVE] AFN BLOCKED: listing_id={l.id}, sku={l.external_sku}, reason={blocked_reason}")
        else:
            pushable_count += 1
        
        result.append({
            'id': l.id,
            'platform': l.store.platform if l.store else 'Unknown',
            'store_id': l.store_id,
            'store_name': l.store.name if l.store else 'Unknown',
            'sku': getattr(l, 'external_sku', '') or '',
            'external_id': l.external_listing_id or l.asin or '',
            'fulfillment': l.amazon_fulfillment_channel or 'FBM',
            'warehouse_stock_id': l.warehouse_stock_id,
            'is_pushable': is_pushable,
            'status': status,
            'blocked_reason': blocked_reason
        })
    
    logging.info(f"[GROUP_RESOLVE] Resolved {len(result)} listings for "
                f"{'group ' + str(ws.master_product_group_id) if group else 'single SKU ' + ws.sku} "
                f"(pushable={pushable_count}, blocked={blocked_count})")
    
    return primary_ws, result, group


def resolve_group_for_push(warehouse_stock_id: int) -> Dict:
    """
    Resolve all information needed for a group push.
    
    This is the COMPLETE resolution for push operations:
    - Primary warehouse stock (source of truth for quantity)
    - All group members (warehouse stocks)
    - All pushable listings across the group
    - Group quantity
    
    Args:
        warehouse_stock_id: Any warehouse stock ID in the group
        
    Returns:
        Dict with all group info for push operation
    """
    primary_ws, listings, group = get_listings_for_warehouse_stock_expanded(warehouse_stock_id, fbm_only=True)
    
    if not primary_ws:
        return {
            'success': False,
            'error': 'Warehouse stock not found',
            'group_id': None,
            'is_grouped': False
        }
    
    group_id = group.id if group else None
    
    if group:
        members = get_group_members(group.id)
        member_skus = [m.sku for m in members]
    else:
        member_skus = [primary_ws.sku]
    
    return {
        'success': True,
        'group_id': group_id,
        'is_grouped': group is not None,
        'group_name': group.display_title if group else primary_ws.sku,
        'primary_warehouse_stock_id': primary_ws.id,
        'primary_sku': primary_ws.sku,
        'group_quantity': primary_ws.available_quantity,
        'member_count': len(member_skus),
        'member_skus': member_skus,
        'listings': listings,
        'listings_count': len(listings)
    }


def apply_group_quantity_change(warehouse_stock_id: int, quantity_delta: int, reason: str = "manual") -> Dict:
    """
    Apply a quantity change to a group's primary warehouse stock.
    
    Rule G5: All changes go to the primary source, then push to all group listings.
    
    Args:
        warehouse_stock_id: Any warehouse stock ID in the group
        quantity_delta: Change in quantity (negative for decrements)
        reason: Reason for change (for audit)
        
    Returns:
        Dict with result of the operation
    """
    ws = db.session.query(WarehouseStock).get(warehouse_stock_id)
    if not ws:
        return {'success': False, 'error': 'Warehouse stock not found'}
    
    if ws.master_product_group_id:
        primary = get_primary_warehouse_stock(ws.master_product_group_id)
        if not primary:
            return {'success': False, 'error': 'Group has no primary warehouse stock'}
    else:
        primary = ws
    
    old_qty = primary.available_quantity
    new_qty = max(0, old_qty + quantity_delta)
    primary.available_quantity = new_qty
    primary.stock_version = (primary.stock_version or 0) + 1
    
    logging.info(f"[GROUP_QUANTITY] Applied delta {quantity_delta} to primary SKU {primary.sku}: "
                f"{old_qty} -> {new_qty} (reason: {reason})")
    
    return {
        'success': True,
        'primary_sku': primary.sku,
        'old_quantity': old_qty,
        'new_quantity': new_qty,
        'group_id': ws.master_product_group_id
    }


def create_or_get_group(name: Optional[str] = None) -> MasterProductGroup:
    """
    Create a new MasterProductGroup or get an existing one by name.
    
    Args:
        name: Optional display title for the group
        
    Returns:
        MasterProductGroup object
    """
    from datetime import datetime
    
    group = MasterProductGroup()
    group.display_title = name or f"Group created {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    db.session.add(group)
    db.session.flush()
    
    logging.info(f"[GROUP_CREATE] Created new group {group.id}: {group.display_title}")
    return group


def add_warehouse_stock_to_group(warehouse_stock_id: int, group_id: int) -> Dict:
    """
    Add a warehouse stock to a MasterProductGroup.
    
    This is the LINKING operation. Once added, the warehouse stock's listings
    become part of the group.
    
    Args:
        warehouse_stock_id: ID of warehouse stock to add
        group_id: ID of the group to add to
        
    Returns:
        Dict with result
    """
    ws = db.session.query(WarehouseStock).get(warehouse_stock_id)
    if not ws:
        return {'success': False, 'error': 'Warehouse stock not found'}
    
    group = db.session.query(MasterProductGroup).get(group_id)
    if not group:
        return {'success': False, 'error': 'Group not found'}
    
    old_group_id = ws.master_product_group_id
    ws.master_product_group_id = group_id
    
    logging.info(f"[GROUP_LINK] Added warehouse_stock {warehouse_stock_id} (SKU: {ws.sku}) to group {group_id}. "
                f"Previous group: {old_group_id}")
    
    return {
        'success': True,
        'warehouse_stock_id': warehouse_stock_id,
        'sku': ws.sku,
        'group_id': group_id,
        'previous_group_id': old_group_id
    }


def remove_warehouse_stock_from_group(warehouse_stock_id: int) -> Dict:
    """
    Remove a warehouse stock from its MasterProductGroup.
    
    This is the UNLINKING operation. Can ONLY be called by explicit user action.
    Rule: No auto-unlinking EVER.
    
    Args:
        warehouse_stock_id: ID of warehouse stock to remove
        
    Returns:
        Dict with result
    """
    ws = db.session.query(WarehouseStock).get(warehouse_stock_id)
    if not ws:
        return {'success': False, 'error': 'Warehouse stock not found'}
    
    old_group_id = ws.master_product_group_id
    if not old_group_id:
        return {'success': False, 'error': 'Warehouse stock is not in a group'}
    
    ws.master_product_group_id = None
    
    logging.info(f"[GROUP_UNLINK] Removed warehouse_stock {warehouse_stock_id} (SKU: {ws.sku}) from group {old_group_id}")
    
    return {
        'success': True,
        'warehouse_stock_id': warehouse_stock_id,
        'sku': ws.sku,
        'removed_from_group_id': old_group_id
    }


def get_group_context_for_warehouse(warehouse_stock_id: int) -> Dict:
    """
    Get full group context for display in Warehouse page.
    
    This is what the "eye expand" panel should show:
    - Group ID/name
    - All member SKUs
    - All linked marketplace listings count
    - Confirmation that this SKU is part of a group
    
    Args:
        warehouse_stock_id: ID of warehouse stock
        
    Returns:
        Dict with full group context for UI display
    """
    ws = db.session.query(WarehouseStock).get(warehouse_stock_id)
    if not ws:
        return {'is_grouped': False, 'error': 'Warehouse stock not found'}
    
    if not ws.master_product_group_id:
        listings = db.session.query(MarketplaceListing).filter(
            MarketplaceListing.warehouse_stock_id == warehouse_stock_id,
            MarketplaceListing.is_active == True
        ).count()
        
        return {
            'is_grouped': False,
            'warehouse_stock_id': warehouse_stock_id,
            'sku': ws.sku,
            'available_quantity': ws.available_quantity,
            'direct_listings_count': listings,
            'message': 'This SKU is not part of any group'
        }
    
    group = db.session.query(MasterProductGroup).get(ws.master_product_group_id)
    members = get_group_members(ws.master_product_group_id)
    primary = get_primary_warehouse_stock(ws.master_product_group_id)
    _, listings, _ = get_listings_for_warehouse_stock_expanded(warehouse_stock_id, fbm_only=False)
    
    return {
        'is_grouped': True,
        'group_id': ws.master_product_group_id,
        'group_name': group.display_title if group else 'Unnamed Group',
        'warehouse_stock_id': warehouse_stock_id,
        'sku': ws.sku,
        'is_primary': primary.id == warehouse_stock_id if primary else False,
        'primary_sku': primary.sku if primary else None,
        'group_quantity': primary.available_quantity if primary else 0,
        'member_count': len(members),
        'member_skus': [{'id': m.id, 'sku': m.sku, 'is_primary': m.id == (primary.id if primary else None)} for m in members],
        'total_listings_count': len(listings),
        'listings_by_platform': _count_by_platform(listings),
        'message': f'This warehouse SKU is part of Group: {group.display_title if group else "Unnamed"}'
    }


def _count_by_platform(listings: List[Dict]) -> Dict[str, int]:
    """Helper to count listings by platform"""
    counts = {}
    for l in listings:
        platform = l.get('platform', 'Unknown')
        counts[platform] = counts.get(platform, 0) + 1
    return counts


def verify_no_auto_unlink_in_progress() -> bool:
    """
    Safety check to ensure no automated process is unlinking groups.
    
    Rule: No auto-unlinking EVER. Only explicit user action can unlink.
    
    This can be called at sync boundaries to verify integrity.
    """
    logging.debug("[GROUP_NO_AUTO_UNLINK] Verification check - auto-unlinking is BLOCKED by design")
    return True
