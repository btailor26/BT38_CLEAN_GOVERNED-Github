"""Keep the authority-backed FBM bell action count on logical commercial orders.

Historical MarketplaceOrder provider-line siblings are retained for audit, but
must not become separate outstanding dispatch actions. If the existing bell
projection already contains a persisted shipment lifecycle for an order, every
stale Ready/Partially-dispatched sale sibling for that logical order is retired.

This wraps only the existing authority-backed bell reader. It adds no DB query,
marketplace/provider read, polling, scheduling, write, order import or shipment
system.
"""
from __future__ import annotations

from flask import jsonify

from services import governed_fbm_ready_landing_alignment as ready_alignment


_READY_LABELS = {"get ready to dispatch", "partially dispatched"}
_PROGRESS_LABELS = {
    "shipped",
    "picked up",
    "in transit",
    "out for delivery",
    "delivered",
}


def _identity(record: dict) -> tuple[str, str] | None:
    order_id = str(record.get("order_id") or "").strip()
    if not order_id:
        return None
    return (
        str(record.get("platform") or "").strip().lower(),
        order_id,
    )


def _collapse_logical_actions(records: list[dict]) -> list[dict]:
    """Retire progressed orders and keep one dispatch action per logical order."""
    progressed: set[tuple[str, str]] = set()
    for record in records:
        identity = _identity(record)
        if identity is None:
            continue
        label = str(record.get("status_label") or "").strip().lower()
        if label in _PROGRESS_LABELS:
            progressed.add(identity)

    seen_ready: set[tuple[str, str]] = set()
    collapsed: list[dict] = []
    for record in records:
        identity = _identity(record)
        label = str(record.get("status_label") or "").strip().lower()
        is_ready_action = (
            identity is not None
            and record.get("requires_action") is True
            and label in _READY_LABELS
        )

        if is_ready_action:
            if identity in progressed or identity in seen_ready:
                continue
            seen_ready.add(identity)

        collapsed.append(record)

    return collapsed


def install_governed_fbm_logical_action_count_alignment() -> None:
    original = ready_alignment._event_only_bell_reader
    if getattr(original, "_bt38_logical_action_count_aligned", False):
        return

    def aligned_bell_reader():
        response = original()
        if isinstance(response, tuple):
            return response
        payload = response.get_json(silent=True) if hasattr(response, "get_json") else None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return response

        records = _collapse_logical_actions(list(payload.get("records") or []))
        payload["records"] = records
        payload["action_count"] = sum(
            1 for record in records if record.get("requires_action") is True
        )
        payload["latest_event_at"] = records[0].get("created_at") if records else None
        payload["logical_action_projection"] = True
        return jsonify(payload)

    aligned_bell_reader._bt38_logical_action_count_aligned = True
    ready_alignment._event_only_bell_reader = aligned_bell_reader


install_governed_fbm_logical_action_count_alignment()
