"""
READ-ONLY SKELETON — ebay_service.py

INTENDED RESPONSIBILITY:
Handle all eBay API interactions for inventory management.
Manage eBay UK listings and quantity synchronization.
Coordinate with eBay Trading API and Inventory API.

STATUS: Skeleton only — no live logic implemented.
"""


def get_ebay_inventory(item_id: str = None):
    """
    FUTURE: Fetch eBay inventory levels.
    
    Args:
        item_id: Optional eBay ItemID filter
    
    EXTERNAL CALL: eBay Inventory API
    READ PATH: No modifications to eBay
    """
    raise NotImplementedError("get_ebay_inventory not implemented")


def push_ebay_quantity(item_id: str, quantity: int):
    """
    FUTURE: Update eBay listing quantity.
    
    Args:
        item_id: eBay ItemID
        quantity: New quantity to set
    
    EXTERNAL CALL: eBay Trading API ReviseInventoryStatus
    WRITE PATH: Modifies eBay listing
    """
    raise NotImplementedError("push_ebay_quantity not implemented")


def batch_push_ebay_quantities(item_quantity_map: dict):
    """
    FUTURE: Batch update multiple eBay quantities.
    
    Args:
        item_quantity_map: Dict of {item_id: quantity}
    
    EXTERNAL CALL: eBay Bulk Inventory API
    WRITE PATH: Modifies multiple eBay listings
    """
    raise NotImplementedError("batch_push_ebay_quantities not implemented")


def get_listing_details(item_id: str):
    """
    FUTURE: Get current listing details from eBay.
    
    Args:
        item_id: eBay ItemID
    
    EXTERNAL CALL: eBay Trading API GetItem
    READ PATH: No modifications
    """
    raise NotImplementedError("get_listing_details not implemented")


def validate_listing_for_push(item_id: str) -> dict:
    """
    FUTURE: Preflight validation before push.
    
    Args:
        item_id: eBay ItemID
    
    Returns:
        Validation result dict
    
    READ PATH: Validation logic only
    """
    raise NotImplementedError("validate_listing_for_push not implemented")


def remediate_price_issue(item_id: str, remediation_data: dict):
    """
    FUTURE: Apply price remediation to eBay listing.
    
    Args:
        item_id: eBay ItemID
        remediation_data: Price fix details
    
    EXTERNAL CALL: eBay Trading API ReviseItem
    WRITE PATH: Modifies eBay listing price
    """
    raise NotImplementedError("remediate_price_issue not implemented")
