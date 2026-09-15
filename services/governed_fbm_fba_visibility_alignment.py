"""Keep FBA/AFN as a separate read-only truth surface from the FBM workspace.

FBM owns its existing lifecycle controller and its three-argument presentation
injector. FBA/AFN must not patch that injector, add rows to the FBM table, query
a second history snapshot, or create another page authority. The existing FBA
truth link remains owned by governed_fbm_dispatch_queue_alignment.

The small lifecycle helpers below remain because the existing persisted-status
alignment composes with them. They inspect an already supplied order row only;
they do not query, fetch, poll, write, or create another authority.

No marketplace/provider read, polling, write, inventory mutation or Warehouse
change is introduced here.
"""
from __future__ import annotations

from services import governed_fbm_dispatch_queue_alignment as dispatch_queue


_FBA_TYPES = {"FBA", "AFN"}
_FBA_DISPATCHED = {
    "shipped",
    "dispatched",
    "delivered",
    "fulfilled",
    "completed",
    "partially_shipped",
    "partiallyshipped",
    "picked_up_by_carrier",
    "pickedupbycarrier",
    "in_transit",
    "intransit",
    "out_for_delivery",
    "outfordelivery",
}


def _status(row) -> str:
    return str(getattr(row, "status", "") or "").strip().lower()


def _fulfillment(row) -> str:
    return str(getattr(row, "fulfillment_type", "") or "").strip().upper()


def _queue_for(row) -> str | None:
    """Classify one already-loaded persisted FBA/AFN row for lifecycle display."""
    if _fulfillment(row) not in _FBA_TYPES:
        return None
    status = _status(row)
    if status == "pending":
        return "pending"
    if status in _FBA_DISPATCHED:
        return "fba"
    return None


def _install() -> None:
    """Retire the legacy FBA-row injector without changing FBM presentation."""
    if getattr(dispatch_queue, "_bt38_fba_visibility_patched", False):
        return

    # Deliberately do not replace dispatch_queue._inject. Its stable contract is
    # _inject(html, payload, fba_count). The previous FBA overlay replaced it
    # with a five-argument callable while the FBM route still called three,
    # causing /fbm to fail at runtime. FBA remains available through the
    # existing read-only truth link rendered by the FBM lifecycle controller.
    dispatch_queue._bt38_fba_visibility_patched = True


_install()
