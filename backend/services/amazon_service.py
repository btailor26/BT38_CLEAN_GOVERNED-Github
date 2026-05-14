"""
READ-ONLY SKELETON — amazon_service.py

INTENDED RESPONSIBILITY:
Handle all Amazon SP-API interactions for inventory management.
Manage FBA inventory reads and FBM listing updates.
Coordinate with Amazon Seller Central via SP-API.

STATUS: Skeleton only — no live logic implemented.
"""


def get_fba_inventory(sku: str = None):
    """
    FUTURE: Fetch FBA inventory levels from Amazon.
    
    Args:
        sku: Optional SKU filter
    
    EXTERNAL CALL: Amazon SP-API FBA Inventory endpoint
    READ PATH: No modifications to Amazon
    """
    raise NotImplementedError("get_fba_inventory not implemented")


def push_fbm_quantity(sku: str, quantity: int):
    """
    FUTURE: Update FBM listing quantity on Amazon.
    
    Args:
        sku: Seller SKU
        quantity: New quantity to set
    
    EXTERNAL CALL: Amazon SP-API Listings endpoint
    WRITE PATH: Modifies Amazon listing
    """
    raise NotImplementedError("push_fbm_quantity not implemented")


def batch_push_fbm_quantities(sku_quantity_map: dict):
    """
    FUTURE: Batch update multiple FBM quantities.
    
    Args:
        sku_quantity_map: Dict of {sku: quantity}
    
    EXTERNAL CALL: Amazon SP-API Feeds endpoint
    WRITE PATH: Modifies multiple Amazon listings
    """
    raise NotImplementedError("batch_push_fbm_quantities not implemented")


def get_listing_status(sku: str):
    """
    FUTURE: Get current listing status from Amazon.
    
    Args:
        sku: Seller SKU
    
    EXTERNAL CALL: Amazon SP-API Listings endpoint
    READ PATH: No modifications
    """
    raise NotImplementedError("get_listing_status not implemented")


def classify_fulfillment_channel(listing_data: dict) -> str:
    """
    FUTURE: Determine if listing is FBA (AFN) or FBM (MFN).
    
    Args:
        listing_data: Listing data from Amazon
    
    Returns:
        'AFN' for FBA, 'MFN' for FBM
    
    READ PATH: Classification logic only
    """
    raise NotImplementedError("classify_fulfillment_channel not implemented")


def create_mcf_order(order_data: dict):
    """
    FUTURE: Create Multi-Channel Fulfillment order.
    
    Args:
        order_data: MCF order details
    
    EXTERNAL CALL: Amazon Fulfillment Outbound API
    WRITE PATH: Creates fulfillment order
    """
    raise NotImplementedError("create_mcf_order not implemented")
