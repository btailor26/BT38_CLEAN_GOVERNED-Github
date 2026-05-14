"""
READ-ONLY SKELETON — smart_push_service.py

INTENDED RESPONSIBILITY:
Orchestrate inventory push operations to connected marketplaces.
Coordinate between warehouse stock levels and marketplace listings.
Route push requests to appropriate marketplace-specific services.

STATUS: Skeleton only — no live logic implemented.
"""


def push_sku_to_marketplace(sku: str, quantity: int, marketplace: str):
    """
    FUTURE: Route SKU push to appropriate marketplace service.
    
    Args:
        sku: Warehouse SKU identifier
        quantity: Quantity to push
        marketplace: Target marketplace (amazon_fbm, ebay, etc.)
    
    WRITE PATH: Will call amazon_service or ebay_service
    """
    raise NotImplementedError("push_sku_to_marketplace not implemented")


def push_warehouse_stock(warehouse_stock_id: int):
    """
    FUTURE: Push warehouse stock to all linked marketplace listings.
    
    Args:
        warehouse_stock_id: ID of WarehouseStock record
    
    WRITE PATH: Will update marketplace quantities
    """
    raise NotImplementedError("push_warehouse_stock not implemented")


def batch_push_skus(sku_list: list, marketplace: str):
    """
    FUTURE: Batch push multiple SKUs to a marketplace.
    
    Args:
        sku_list: List of SKU identifiers
        marketplace: Target marketplace
    
    WRITE PATH: Will call marketplace APIs in batch
    """
    raise NotImplementedError("batch_push_skus not implemented")


def get_push_status(job_id: str):
    """
    FUTURE: Check status of a push job.
    
    Args:
        job_id: Unique job identifier
    
    READ PATH: Query job status from queue
    """
    raise NotImplementedError("get_push_status not implemented")


def cancel_pending_push(job_id: str):
    """
    FUTURE: Cancel a pending push job.
    
    Args:
        job_id: Unique job identifier
    
    WRITE PATH: Will modify queue state
    """
    raise NotImplementedError("cancel_pending_push not implemented")
