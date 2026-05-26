from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify

governed_runtime_visibility_bp = Blueprint("governed_runtime_visibility", __name__)


def _config_on(key: str) -> bool:
    from models import SystemConfig

    row = SystemConfig.query.filter_by(key=key).first()
    if not row:
        return False
    return str(row.value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


@governed_runtime_visibility_bp.get("/governed/warehouse/runtime-state")
def governed_warehouse_runtime_state():
    """Lightweight warehouse runtime heartbeat.

    This endpoint must not export MarketplaceListing rows, WarehouseStock rows,
    diagnostics dumps, or hidden overlay payloads. Pages can use it only to know
    whether the governed runtime/fuse-box layer is alive.
    """
    return jsonify({
        "success": True,
        "ok": True,
        "governed": True,
        "visibility_only": True,
        "mode": "heartbeat",
        "runtime_state_lightweight": True,
        "timestamp": datetime.utcnow().isoformat(),
        "fuse_box": {
            "read_only_mode": _config_on("read_only_mode"),
            "dry_run_mode": _config_on("dry_run_mode"),
            "queue_frozen": _config_on("queue_frozen"),
            "sync_enabled": _config_on("sync_enabled"),
            "runtime_sync_enabled": _config_on("runtime_sync_enabled"),
            "marketplace_sync_enabled": _config_on("marketplace_sync_enabled"),
            "manual_sync_enabled": _config_on("manual_sync_enabled"),
            "push_enabled": _config_on("push_enabled"),
            "runtime_push_enabled": _config_on("runtime_push_enabled"),
            "marketplace_push_enabled": _config_on("marketplace_push_enabled"),
            "manual_push_enabled": _config_on("manual_push_enabled"),
        },
        "message": "Runtime heartbeat only. No listing or warehouse rows are exported from this endpoint.",
    })
