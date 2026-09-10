"""Preserve Amazon Pending visibility in the existing FBM/FBA presentation.

Amazon ORDER_CHANGE can be successfully processed internally while Amazon's
marketplace lifecycle is still Pending. Some historical/current MarketplaceOrder
rows therefore carry the internal status ``processed`` even though the order has
not shipped. The existing FBA visibility layer must not treat that internal
processing marker as a marketplace lifecycle transition.

Presentation only: no marketplace read, polling, worker, inventory mutation or
new order state is introduced.
"""
from __future__ import annotations

from services import governed_fbm_fba_visibility_alignment as fba_visibility


def _install() -> None:
    if getattr(fba_visibility, "_bt38_pending_processed_aligned", False):
        return

    original_queue_for = fba_visibility._queue_for

    def aligned_queue_for(row):
        queue = original_queue_for(row)
        if queue is not None:
            return queue

        if fba_visibility._fulfillment(row) not in fba_visibility._FBA_TYPES:
            return None

        status = fba_visibility._status(row)
        if status != "processed":
            return None

        # ``processed`` is BT38 intake completion, not proof that Amazon cleared
        # Pending. Until persisted shipment/lifecycle evidence exists, keep the
        # same FBA/AFN order in Pending. When Amazon later persists a real
        # shipped/delivery state, the original FBA mapping moves it to FBA.
        if (
            getattr(row, "shipped_at", None) is None
            and not str(getattr(row, "tracking_number", "") or "").strip()
            and not str(getattr(row, "carrier", "") or "").strip()
        ):
            return "pending"

        return None

    fba_visibility._queue_for = aligned_queue_for
    fba_visibility._bt38_pending_processed_aligned = True


_install()
