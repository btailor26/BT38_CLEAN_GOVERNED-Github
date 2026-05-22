"""
BT38 runtime gate compatibility wrapper.

This file no longer owns runtime execution authority.

Authority now lives in:
services/runtime_action_guard.py

runtime_gate.py only exists to preserve compatibility for:
- governed_execution.py
- older governed command paths
- existing tests/imports
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from services.runtime_action_guard import is_runtime_action_allowed

APPROVED_AMAZON_FBM_PUSH_TYPE = "amazon_fbm_inventory_push"

RUNTIME_GATE_MESSAGE = (
    "BT38 runtime execution is controlled by the settings fuse box."
)


@dataclass
class RuntimeCommand:
    action: str
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _resolve_action_type(command: RuntimeCommand) -> str:
    action = str(getattr(command, "action", "") or "").strip().lower()

    if "push" in action:
        return "push"

    if "import" in action:
        return "import"

    if "sync" in action:
        return "sync"

    return action


def _resolve_store(command: RuntimeCommand):
    try:
        from models import Store

        payload = getattr(command, "payload", {}) or {}

        store_id = (
            payload.get("store_id")
            or payload.get("store")
            or payload.get("storeId")
        )

        if not store_id:
            return None

        return Store.query.get(int(store_id))

    except Exception:
        return None


def is_runtime_allowed(command: RuntimeCommand):
    action_type = _resolve_action_type(command)
    store = _resolve_store(command)

    metadata = getattr(command, "metadata", {}) or {}
    payload = getattr(command, "payload", {}) or {}

    manual = bool(
        metadata.get("manual")
        or metadata.get("manual_trigger")
        or payload.get("manual")
        or payload.get("manual_trigger")
    )

    result = is_runtime_action_allowed(
        store=store,
        action_type=action_type,
        manual=manual,
        context={
            "source": "runtime_gate",
            "command_action": getattr(command, "action", None),
        },
    )

    return bool(result.get("allowed", False))


def assert_runtime_allowed(command: RuntimeCommand):
    action_type = _resolve_action_type(command)
    store = _resolve_store(command)

    metadata = getattr(command, "metadata", {}) or {}
    payload = getattr(command, "payload", {}) or {}

    manual = bool(
        metadata.get("manual")
        or metadata.get("manual_trigger")
        or payload.get("manual")
        or payload.get("manual_trigger")
    )

    result = is_runtime_action_allowed(
        store=store,
        action_type=action_type,
        manual=manual,
        context={
            "source": "runtime_gate_assert",
            "command_action": getattr(command, "action", None),
        },
    )

    if not result.get("allowed", False):
        raise RuntimeError(result.get("reason", RUNTIME_GATE_MESSAGE))

    return result
