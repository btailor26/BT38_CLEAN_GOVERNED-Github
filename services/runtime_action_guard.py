"""BT38 fuse-box runtime interpreter.

Single authority rule:
SystemConfig is the fuse box. It decides whether push/import/sync can run.

This module is NOT a second authority layer.
It does not read environment execution switches.
It does not start workers.
It does not enqueue jobs.
It does not call marketplaces.
It only interprets the fuse box and store-level permissions.

Required path:
UI shortcut
-> governed route
-> this fuse-box interpreter
-> governed execution
-> marketplace adapter
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


def _falsey(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    return str(value).strip().lower() in {"0", "false", "no", "off", "disabled", "none", ""}


def _store_value(store: Any, attr: str, default: Any = None) -> Any:
    return getattr(store, attr, default) if store is not None else default


def _store_flag_disabled(store: Any, attr: str) -> bool:
    if store is None or not hasattr(store, attr):
        return False
    return _falsey(getattr(store, attr))


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

    All push/import/sync decisions must be made here from the fuse box.
    Store flags are treated as store-level fuse permissions, not separate authority.
    """

    action = str(action_type or "").strip().lower()
    manual = bool(manual)
    context = context or {}

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
        return _blocked(store, action, manual, f"Store fuse store_mode={store_mode} blocks {action}")

    if action == "push":
        if _store_flag_disabled(store, "auto_push_enabled"):
            return _blocked(store, action, manual, "Store fuse auto_push_enabled is OFF")

    if action == "sync":
        if _store_flag_disabled(store, "fbm_sync_enabled"):
            return _blocked(store, action, manual, "Store fuse fbm_sync_enabled is OFF")

    if action == "import":
        if _store_flag_disabled(store, "fba_import_enabled"):
            return _blocked(store, action, manual, "Store fuse fba_import_enabled is OFF")

    if not _store_value(store, "api_key"):
        return _blocked(store, action, manual, "Store credentials are missing")

    platform = str(_store_value(store, "platform", "") or "").strip().lower()
    fulfillment_type = str(_store_value(store, "fulfillment_type", "") or "").strip().upper()

    if action == "push" and ("fba" in platform or fulfillment_type == "FBA"):
        return _blocked(store, action, manual, "FBA/AFN is read-only and cannot push")

    return _allowed(store, action, manual)
