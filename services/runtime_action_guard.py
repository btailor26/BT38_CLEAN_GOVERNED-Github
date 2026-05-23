"""BT38 fuse-box runtime interpreter.

Single authority rule:
SystemConfig is the execution authority.

Store fields are capability/state checks only:
- store_mode
- is_active
- api_key

MarketplaceListing fields are operational safety checks only:
- sync_quantity
- push_state
- amazon_fulfillment_channel

This module does not read env execution switches.
This module does not start workers.
This module does not enqueue jobs.
This module does not call marketplaces.
"""

from __future__ import annotations

from typing import Any, Dict


READ_ONLY_ACTIONS = {"preview", "read", "read_only", "status", "audit"}
RUNTIME_ACTIONS = {"push", "sync", "import"}
VALID_ACTIONS = READ_ONLY_ACTIONS | RUNTIME_ACTIONS


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value is True
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "live"}


def _store_value(store: Any, attr: str, default: Any = None) -> Any:
    return getattr(store, attr, default) if store is not None else default


def _config_value(key: str, default: Any = "false") -> Any:
    from models import SystemConfig

    row = SystemConfig.query.filter_by(key=key).first()
    if row is None:
        return default
    return row.value


def _config_on(key: str, default: bool = False) -> bool:
    return _truthy(_config_value(key, "true" if default else "false"))


def _blocked(store: Any, action_type: str, manual: bool, reason: str) -> Dict[str, Any]:
    return {
        "allowed": False,
        "reason": reason,
        "action_type": action_type,
        "manual": bool(manual),
        "store_id": _store_value(store, "id"),
        "store_name": _store_value(store, "name"),
        "fuse_box_checked": True,
        "source": "SystemConfig fuse box",
    }


def _allowed(store: Any, action_type: str, manual: bool, reason: str = "Fuse box allowed action") -> Dict[str, Any]:
    return {
        "allowed": True,
        "reason": reason,
        "action_type": action_type,
        "manual": bool(manual),
        "store_id": _store_value(store, "id"),
        "store_name": _store_value(store, "name"),
        "fuse_box_checked": True,
        "source": "SystemConfig fuse box",
    }


def _required_fuses(action_type: str, manual: bool) -> list[str]:
    if action_type == "push":
        keys = ["push_enabled", "runtime_push_enabled", "marketplace_push_enabled"]
        if manual:
            keys.append("manual_push_enabled")
        return keys

    if action_type == "import":
        keys = ["import_enabled", "runtime_import_enabled", "marketplace_import_enabled"]
        if manual:
            keys.append("manual_import_enabled")
        return keys

    if action_type == "sync":
        keys = ["sync_enabled", "runtime_sync_enabled", "marketplace_sync_enabled"]
        if manual:
            keys.append("manual_sync_enabled")
        return keys

    return []


def is_runtime_action_allowed(store, action_type, manual=False, context=None):
    """Single governed runtime decision point.

    SystemConfig decides execution.
    Store/listing values only prove whether the requested action is structurally safe.
    """

    action = str(action_type or "").strip().lower()
    manual = bool(manual)

    if action not in VALID_ACTIONS:
        return _blocked(store, action, manual, "Unsupported runtime action")

    if action in READ_ONLY_ACTIONS:
        return _allowed(store, action, manual, "Read-only action allowed")

    if _config_on("read_only_mode", default=False):
        return _blocked(store, action, manual, "Fuse box read_only_mode is ON")

    if _config_on("queue_frozen", default=False) and not manual:
        return _blocked(store, action, manual, "Fuse box queue_frozen is ON")

    for key in _required_fuses(action, manual):
        if not _config_on(key, default=False):
            return _blocked(store, action, manual, f"Fuse box {key} is OFF")

    if store is None:
        return _blocked(store, action, manual, "Store is required")

    if not bool(_store_value(store, "is_active", False)):
        return _blocked(store, action, manual, "Store is inactive")

    store_mode = str(_store_value(store, "store_mode", "safe") or "safe").strip().lower()
    if store_mode != "live":
        return _blocked(store, action, manual, f"Store state store_mode={store_mode} blocks {action}")

    if not _store_value(store, "api_key"):
        return _blocked(store, action, manual, "Store credentials are missing")

    platform = str(_store_value(store, "platform", "") or "").strip().lower()
    fulfillment_type = str(_store_value(store, "fulfillment_type", "") or "").strip().upper()

    if action == "push" and ("fba" in platform or fulfillment_type == "FBA"):
        return _blocked(store, action, manual, "FBA/AFN is read-only and cannot push")

    return _allowed(store, action, manual)
