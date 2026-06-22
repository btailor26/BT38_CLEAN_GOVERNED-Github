from extensions import db
from models import WarehouseStock, MarketplaceOrder, MarketplaceListing


def run_warehouse_snapshot_reconciliation(stock_id: int):
    """
    READ-ONLY reconciliation layer.

    Purpose:
    - Detect drift between MarketplaceOrder ledger and WarehouseStock
    - Report differences
    - NEVER mutate stock

    Source of truth:
    - mutate_warehouse_stock_from_order_line ONLY
    """

    stock = WarehouseStock.query.get(stock_id)

    if not stock:
        return {
            "success": False,
            "error": "warehouse_stock_not_found",
            "stock_id": stock_id
        }

    listings = MarketplaceListing.query.filter_by(
        warehouse_stock_id=stock_id
    ).all()

    skus = [l.external_sku for l in listings if l.external_sku]

    orders = (
        MarketplaceOrder.query
        .filter(MarketplaceOrder.sku.in_(skus))
        .order_by(MarketplaceOrder.created_at.asc())
        .all()
    )

    total_sales = sum(
        o.quantity for o in orders
        if (o.status or "").lower() in ["sale", "completed"]
    )

    total_returns = sum(
        o.quantity for o in orders
        if (o.status or "").lower() in ["return", "refunded"]
    )

    computed = total_sales - total_returns

    return {
        "success": True,
        "stock_id": stock_id,
        "ledger_sales": total_sales,
        "ledger_returns": total_returns,
        "computed_quantity": computed,
        "current_quantity": stock.available_quantity,
        "drift": stock.available_quantity - computed,
        "note": "READ_ONLY_AUDIT_MODE"
    }
