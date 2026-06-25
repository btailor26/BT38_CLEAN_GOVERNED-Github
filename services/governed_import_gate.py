from flask import current_app

from services.governed_marketplace_order_import import run_governed_marketplace_order_import
from services.governed_amazon_inventory_import import run_governed_amazon_inventory_import
from services.governed_ebay_inventory_import import run_governed_ebay_inventory_import


def run_import_cycle():
    """
    SINGLE SOURCE IMPORT PIPELINE (WAREHOUSE-ALIGNED)
    """

    with current_app.app_context():

        amazon = run_governed_amazon_inventory_import()
        ebay = run_governed_ebay_inventory_import()
        orders = run_governed_marketplace_order_import()

        return {
            "amazon": amazon,
            "ebay": ebay,
            "orders": orders,
            "status": "import_complete"
        }
