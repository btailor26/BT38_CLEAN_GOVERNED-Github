from extensions import db
from models import SystemConfig

def _enabled(key):
    row = SystemConfig.query.filter_by(key=key).first()
    return bool(row.value) if row else False


def governed_execution_gate(action_type, fn, *args, **kwargs):
    """
    SINGLE ENTRY POINT FOR ALL MARKETPLACE EXECUTION
    """

    if not _enabled("execution_enabled"):
        return {"ok": False, "blocked": True, "reason": "execution_disabled"}

    if action_type == "amazon_import" and not _enabled("amazon_import_enabled"):
        return {"ok": False, "blocked": True, "reason": "amazon_disabled"}

    if action_type == "ebay_import" and not _enabled("ebay_import_enabled"):
        return {"ok": False, "blocked": True, "reason": "ebay_disabled"}

    if action_type == "warehouse_sync" and not _enabled("warehouse_sync_enabled"):
        return {"ok": False, "blocked": True, "reason": "warehouse_disabled"}

    return fn(*args, **kwargs)
