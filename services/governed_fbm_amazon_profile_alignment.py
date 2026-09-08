"""Restore exact Amazon profile hydration to the bounded FBM workspace.

The bounded FBM page intentionally reads a small visible order window, but its
_profile_map replacement reduced Amazon classification to DB-only lookup. New
Amazon FBM orders could therefore render before FBMOrderProfile existed, losing
Prime/SFP lock, marketplace promise and the existing shipped-order readbacks.

This alignment keeps the bounded page and existing Amazon profile authority. On
the first profile-map read in an FBM request it hydrates only visible/selected
Amazon rows whose profile is missing or classification is incomplete. The
existing get_or_refresh_amazon_profile path owns Amazon reads and persistence;
no worker, poller, order importer, shipment table or marketplace write is added.
Subsequent profile-map reads in the same request (notably health aggregation)
remain DB-only so the health surface never fans out marketplace calls.

A profile-complete Amazon order can still be stale for shipment truth. If that
same visible exact order is already shipped but carrier/tracking is missing, the
first bounded FBM read reuses the existing Orders v2026 PACKAGES readback for
that exact order only. This does not refresh the whole profile, scan historical
orders, create a shipment, or introduce a background recovery path.

When Amazon's existing exact package readback has already advanced an existing
MarketplaceOrder lifecycle, the FBM presentation reuses that persisted lifecycle
for the existing journey badges if no physical BT38 shipment exists. Plain
"shipped" remains dispatch-only and does not invent a carrier milestone.
"""
from __future__ import annotations

from flask import g

from extensions import db
from services.fbm_amazon_order_profile import (
    AmazonOrderProfileError,
    get_or_refresh_amazon_profile,
)
import services.governed_fbm_page_alignment as _page_alignment


_original_profile_map = _page_alignment._profile_map
_original_render_template = _page_alignment.render_template


def _amazon_row(row) -> bool:
    store = getattr(row, "store", None)
    return str(getattr(store, "platform", "") or "").strip().lower() == "amazon"


def _profile_complete(profile) -> bool:
    if profile is None:
        return False
    # Prime classification is the routing lock. Fulfilment channel is the
    # seller-fulfilled authority used by the workspace eligibility guard.
    return (
        getattr(profile, "is_prime", None) is not None
        and bool(str(getattr(profile, "fulfillment_channel", "") or "").strip())
    )


def _needs_exact_tracking_readback(row) -> bool:
    if not _amazon_row(row):
        return False
    status = (
        str(getattr(row, "status", "") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if status not in {"shipped", "partially_shipped", "partiallyshipped"}:
        return False
    carrier = str(getattr(row, "carrier", "") or "").strip()
    tracking = str(getattr(row, "tracking_number", "") or "").strip()
    return not carrier or not tracking


def _read_exact_missing_tracking(row) -> bool:
    if not _needs_exact_tracking_readback(row):
        return False
    store = getattr(row, "store", None)
    if store is None or row.marketplace_order_id is None:
        return False
    from services.governed_amazon_tracking_readback import (
        hydrate_amazon_tracking_for_order,
    )

    result = hydrate_amazon_tracking_for_order(
        store=store,
        marketplace_order_id=str(row.marketplace_order_id),
        source="fbm_visible_missing_tracking",
    )
    return bool(result.get("success"))


def _governed_profile_map(rows):
    profiles = _original_profile_map(rows)

    # bounded_fbm_page calls _profile_map for its visible rows before health;
    # bounded_shipping_options calls it for the explicitly selected rows. Only
    # that first request-local call may hydrate/read Amazon. Later calls stay
    # DB-only so the health surface never fans out marketplace calls.
    if getattr(g, "_bt38_fbm_amazon_profile_hydration_checked", False):
        return profiles
    g._bt38_fbm_amazon_profile_hydration_checked = True

    refreshed = False
    for row in rows:
        try:
            if not _amazon_row(row) or row.store_id is None or not row.marketplace_order_id:
                continue
            key = (int(row.store_id), str(row.marketplace_order_id))
            if _profile_complete(profiles.get(key)):
                # A complete Prime/MFN profile does not prove shipment package
                # truth is complete. Reuse the exact existing Amazon PACKAGES
                # reader only for this visible shipped row when tracking facts
                # are still absent.
                _read_exact_missing_tracking(row)
                continue
            get_or_refresh_amazon_profile(row)
            refreshed = True
        except AmazonOrderProfileError:
            # Hydration is temporary compatibility only. Any failed unit must
            # be rolled back before the next visible row or page DB read.
            db.session.rollback()
            continue
        except Exception:
            # Marketplace/readback/autoflush failures must never poison the
            # shared request session or take down the FBM desk.
            db.session.rollback()
            continue

    return _original_profile_map(rows) if refreshed else profiles


def _amazon_marketplace_journey_state(order):
    if order is None or not _amazon_row(order):
        return None
    status = (
        str(getattr(order, "status", "") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    # Only real post-dispatch lifecycle evidence lights a journey milestone.
    # Amazon "shipped" alone remains dispatch truth with milestones unavailable.
    return {
        "picked_up": "accepted",
        "pickedup": "accepted",
        "accepted": "accepted",
        "carrier_accepted": "accepted",
        "collected": "accepted",
        "in_transit": "in_transit",
        "intransit": "in_transit",
        "out_for_delivery": "out_for_delivery",
        "outfordelivery": "out_for_delivery",
        "delivered": "delivered",
    }.get(status)


def _governed_render_template(template_name, *args, **context):
    if template_name == "fbm.html":
        original_orders = context.get("orders") or []
        aligned_orders = []
        changed = False
        for item in original_orders:
            if not isinstance(item, dict) or item.get("shipment") is not None:
                aligned_orders.append(item)
                continue
            journey_state = _amazon_marketplace_journey_state(item.get("order"))
            if not journey_state:
                aligned_orders.append(item)
                continue
            aligned = dict(item)
            aligned["shipment_state"] = journey_state
            aligned_orders.append(aligned)
            changed = True
        if changed:
            context = dict(context)
            context["orders"] = aligned_orders
    return _original_render_template(template_name, *args, **context)


if not getattr(_page_alignment, "_bt38_amazon_profile_hydration_restored", False):
    _page_alignment._profile_map = _governed_profile_map
    _page_alignment._bt38_amazon_profile_hydration_restored = True

if not getattr(_page_alignment, "_amazon_marketplace_journey_alignment_installed", False):
    _page_alignment.render_template = _governed_render_template
    _page_alignment._amazon_marketplace_journey_alignment_installed = True
