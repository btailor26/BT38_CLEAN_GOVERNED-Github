from extensions import db
from models import SystemConfig

def is_enabled(key: str) -> bool:
    row = SystemConfig.query.filter_by(key=key).first()
    return bool(row.value) if row else False


def governed_import_gate(context: str, fn, *args, **kwargs):
    """
    Single entry gate for ALL import operations.
    """
    if not is_enabled("import_enabled"):
        return {"success": False, "blocked": True, "reason": "import_disabled"}

    if context == "amazon" and not is_enabled("amazon_import_enabled"):
        return {"success": False, "blocked": True, "reason": "amazon_import_disabled"}

    if context == "ebay" and not is_enabled("ebay_import_enabled"):
        return {"success": False, "blocked": True, "reason": "ebay_import_disabled"}

    if context == "warehouse" and not is_enabled("warehouse_import_enabled"):
        return {"success": False, "blocked": True, "reason": "warehouse_import_disabled"}

    return fn(*args, **kwargs)

def governed_import_allowed(context: str) -> bool:
    """
    Compatibility helper used by governed_routes.py.
    Returns whether a governed import context is enabled.
    """
    if not is_enabled("import_enabled"):
        return False

    if context == "amazon":
        return is_enabled("amazon_import_enabled")

    if context == "ebay":
        return is_enabled("ebay_import_enabled")

    if context == "warehouse":
        return is_enabled("warehouse_import_enabled")

    return True
