"""Align FBM shipment presentation to persisted marketplace dispatch truth.

Marketplace dispatch remains a valid fallback when BT38 has no confirmed persisted
physical shipment for the order. A real persisted provider shipment (Packlink,
Amazon Buy Shipping, eBay Shipping, manual or another connected provider) stays the
stronger physical-shipment authority after the selling marketplace reports Shipped.

Unverified/draft provider rows are not physical authority. This matters when a label
attempt times out or is abandoned: stale draft carrier/service choices must not mask
later marketplace dispatch truth or a subsequently recovered marketplace-native label.

This is a read/presentation alignment only: no marketplace/provider reads, writes,
pollers, workers, new tables or duplicate shipment identities are introduced.
"""
from __future__ import annotations

from types import SimpleNamespace


_DISPATCHED_STATES = {
    "shipped",
    "dispatched",
    "partially_shipped",
    "partiallydispatched",
    "fulfilled",
    "completed",
}
_TERMINAL_DELIVERY_STATES = {
    "accepted",
    "carrier_accepted",
    "collected",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "delivered",
}
_UNVERIFIED_SHIPMENT_STATES = {
    "draft",
    "draft_verification_required",
    "verification_required",
    "quote",
    "quoted",
    "pending_verification",
}


def _status(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _platform_label(row) -> str:
    store = getattr(row, "store", None)
    value = str(getattr(store, "platform", "") or "Marketplace").strip()
    if value.lower() == "amazon":
        return "Amazon"
    if value.lower() == "ebay":
        return "eBay"
    return value or "Marketplace"


def _marketplace_has_dispatch_truth(row) -> bool:
    """Read the dispatch facts already persisted on MarketplaceOrder."""
    status = _status(getattr(row, "status", None))
    return bool(
        status in _DISPATCHED_STATES
        or status in _TERMINAL_DELIVERY_STATES
        or getattr(row, "shipped_at", None)
        or str(getattr(row, "tracking_number", None) or "").strip()
    )


def _confirmed_physical_shipment(shipment) -> bool:
    """Return whether a persisted provider row has durable physical authority.

    Merely choosing a provider/carrier/service or creating a verification draft is
    not purchase/dispatch proof. Durable provider identity, tracking, purchase or
    carrier lifecycle evidence is. Marketplace presentation proxies are handled
    separately and are never classified as physical authority here.
    """
    if shipment is None:
        return False
    provider = str(getattr(shipment, "provider", "") or "").strip().lower()
    if provider in {"", "marketplace"}:
        return False

    status = _status(getattr(shipment, "status", None))
    purchase_status = _status(getattr(shipment, "purchase_status", None))
    has_durable_evidence = bool(
        getattr(shipment, "provider_shipment_id", None)
        or getattr(shipment, "tracking_number", None)
        or getattr(shipment, "label_purchased_at", None)
        or getattr(shipment, "marketplace_confirmed_at", None)
        or getattr(shipment, "carrier_accepted_at", None)
        or getattr(shipment, "first_movement_at", None)
        or getattr(shipment, "delivered_at", None)
        or purchase_status in {"purchased", "confirmed", "committed"}
    )
    if status in _UNVERIFIED_SHIPMENT_STATES and not has_durable_evidence:
        return False
    return has_durable_evidence


def _marketplace_shipment(row):
    """Expose persisted marketplace shipment facts only as a presentation fallback.

    Marketplace Shipped proves dispatch, not physical pickup. Marketplace Delivered
    is terminal truth and may complete the lifecycle without invented intermediate
    timestamps. This proxy is never persisted as FBMShipment.
    """
    if not _marketplace_has_dispatch_truth(row):
        return None

    status = _status(getattr(row, "status", None))
    tracking = str(getattr(row, "tracking_number", None) or "").strip() or None
    carrier = str(getattr(row, "carrier", None) or "").strip() or None
    shipped_at = getattr(row, "shipped_at", None)
    changed_at = getattr(row, "updated_at", None) or shipped_at or getattr(row, "created_at", None)
    platform = _platform_label(row)

    carrier_display = carrier or f"{platform} marketplace shipment"
    service_display = "Marketplace dispatch" if tracking else "Tracking pending"

    delivered = status == "delivered"
    pickup_proven = status in {
        "accepted", "carrier_accepted", "collected", "picked_up",
        "in_transit", "out_for_delivery", "delivered",
    }
    movement_proven = status in {"in_transit", "out_for_delivery", "delivered"}

    return SimpleNamespace(
        id=None,
        provider="marketplace",
        provider_shipment_id=None,
        provider_carrier_id=None,
        provider_service_id=None,
        purchase_key=None,
        purchase_status=None,
        carrier=carrier_display,
        service=service_display,
        tracking_number=tracking,
        label_url=None,
        label_format=None,
        label_purchased_at=shipped_at or (changed_at if tracking else None),
        handover_due_at=None,
        carrier_accepted_at=changed_at if pickup_proven and not delivered else None,
        first_movement_at=changed_at if movement_proven and not delivered else None,
        delivered_at=changed_at if delivered else None,
        status=status or "dispatched",
        marketplace_confirmed_at=shipped_at,
        marketplace_confirmation_status="marketplace_authoritative",
        mapping_review=None,
        provider_cases=[],
        _bt38_marketplace_owned=True,
        _bt38_terminal_delivery_proves_prior_milestones=delivered,
    )


def install_governed_fbm_marketplace_dispatch_authority_alignment() -> None:
    import services.governed_fbm_page_alignment as page

    if getattr(page, "_bt38_marketplace_dispatch_authority_aligned", False):
        return

    original_shipment_map = page._shipment_map
    original_route_state = page._route_state

    def aligned_shipment_map(rows):
        # The existing DB selector chooses a persisted shipment candidate. Keep it
        # only when durable DB evidence proves physical authority. A stale draft
        # from a timed-out/abandoned purchase must not override later marketplace
        # dispatch truth.
        existing = original_shipment_map(rows)
        result = {
            key: shipment
            for key, shipment in existing.items()
            if _confirmed_physical_shipment(shipment)
        }
        for row in rows:
            if row.store_id is None or not row.marketplace_order_id:
                continue
            key = (int(row.store_id), str(row.marketplace_order_id))
            if key in result and result[key] is not None:
                continue
            marketplace = _marketplace_shipment(row)
            if marketplace is not None:
                result[key] = marketplace
        return result

    def aligned_route_state(row):
        if _marketplace_has_dispatch_truth(row):
            status = _status(getattr(row, "status", None))
            if status == "delivered":
                return "Delivered"
            if str(getattr(row, "tracking_number", None) or "").strip():
                return "Tracking recorded"
            return "Marketplace dispatched"
        status = _status(getattr(row, "status", None))
        if status in {"pending"}:
            return "Pending"
        if status in {"processed", "confirmed", "unshipped", "order", "ready"}:
            return "Awaiting dispatch"
        current = original_route_state(row)
        return "Awaiting dispatch" if current == "Ready for FBM routing" else current

    # Keep the existing pre-dispatch shipping-mode/provider-choice functions.
    # They describe available purchase routes; they are not allowed to overwrite
    # the physical provider selected by the persisted shipment map after dispatch.
    page._shipment_map = aligned_shipment_map
    page._route_state = aligned_route_state
    page._bt38_marketplace_dispatch_authority_aligned = True
