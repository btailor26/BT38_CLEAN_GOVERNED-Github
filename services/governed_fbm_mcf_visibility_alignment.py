"""Keep MCF lifecycle from overriding the governed FBM page injector.

The FBM lifecycle controller owns the stable three-argument presentation
contract ``_inject(html, payload, fba_count)``.  The retired MCF overlay used an
older five-argument contract and rebuilt a selected-history MCF dataset during
an ordinary /fbm request.  That composition made the page fail before render.

MCF remains its own persisted fulfilment lifecycle.  This compatibility module
only prevents MCF MarketplaceOrder rows from being classified as FBA/AFN by the
existing helper.  It does not query, fetch, poll, write, mutate Warehouse, add a
second page authority, or replace the FBM injector.
"""
from __future__ import annotations

from models import MarketplaceOrder
from services import governed_fbm_dispatch_queue_alignment as dispatch_queue
from services import governed_fbm_fba_visibility_alignment as fba_visibility


def _text(value) -> str:
    return str(value or "").strip()


def _is_mcf_marketplace_row(row: MarketplaceOrder) -> bool:
    if getattr(row, "mcf_order_id", None) is not None:
        return True
    return _text(getattr(row, "marketplace_order_item_id", None)).upper().startswith("MCF-")


def _install() -> None:
    if getattr(dispatch_queue, "_bt38_mcf_visibility_patched", False):
        return

    original_fba_queue_for = fba_visibility._queue_for

    def mcf_safe_fba_queue_for(row):
        if _is_mcf_marketplace_row(row):
            return None
        return original_fba_queue_for(row)

    # Keep the existing classification guard, but deliberately do not replace
    # dispatch_queue._inject.  FBM owns that stable three-argument contract and
    # normal page rendering must not rebuild/query a second MCF history set.
    fba_visibility._queue_for = mcf_safe_fba_queue_for
    dispatch_queue._bt38_mcf_visibility_patched = True


_install()
