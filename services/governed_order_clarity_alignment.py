"""Presentation-only alignment for governed FBM UI.

The marketplace/provider handoff owns collection and persistence. Page GETs must
not recover, reconcile, hydrate, or call marketplace/provider APIs. This module
keeps presentation cleanup separate while installing the existing DB-first
marketplace lifecycle alignment before the FBM page wrapper is bound.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from flask import request
from sqlalchemy import tuple_

_JOURNEY_LABEL_REPLACEMENTS = (("1 · Picked up", "Picked up"), ("2 · In transit", "In transit"), ("3 · Delivered", "Delivered"))
_TRACKING_LINK_STYLE = ('<style id="bt38FbmTrackingLinkAlignment">''.fbm-orders-table td a:has(code),.fbm-orders-table td a:has(code):hover,.fbm-orders-table td a:has(code):focus,.fbm-orders-table .fbm-tracking-journey,.fbm-orders-table .fbm-tracking-journey:hover,.fbm-orders-table .fbm-tracking-journey:focus{text-decoration:none!important;border-bottom:0!important;box-shadow:none!important}.fbm-orders-table td a:has(code) code,.fbm-orders-table .fbm-tracking-journey code{text-decoration:none!important;border-bottom:0!important;box-shadow:none!important}</style>')
_MARKETPLACE_BADGE_STYLE = ('<style id="bt38FbmMarketplaceBadgeAlignment">''.fbm-marketplace-cell{min-width:110px!important}.fbm-marketplace-logo{display:block!important;max-width:82px!important;max-height:36px!important;width:auto!important;height:auto!important;object-fit:contain!important;object-position:left center!important;image-rendering:auto}</style>')
_PROMISE_JOURNEY_SCRIPT = '<script id="bt38FbmPromiseJourneyAlignment" src="/static/js/fbm_delivery_promise_journey_alignment.js"></script>'
_EVENT_SESSION_REFRESH_SCRIPT = '<script id="bt38FbmEventSessionRefreshAlignment" src="/static/js/fbm_event_session_refresh_alignment.js"></script>'
_SCROLL_POSITION_SCRIPT = '<script id="bt38FbmScrollPositionAlignment" src="/static/js/fbm_scroll_position_alignment.js"></script>'

# Restored from the proven delivery-timing implementation at 372980b6... .
# Current rows carry additional data-* attributes, so match them without changing
# the persisted-order identity contract used by the original alignment.
_FBM_ROW_RE = re.compile(
    r'(<tr class="fbm-order-row" data-order-id="(?P<row_id>\d+)"[^>]*>)(?P<body>.*?)(</tr>)',
    re.DOTALL,
)
_SHIPPING_CELL_RE = re.compile(r'<td class="fbm-route-cell">(?P<body>.*?)</td>', re.DOTALL)
_MARKETPLACE_PROMISE_SERVICE_RE = re.compile(
    r'<div class="small text-muted">Marketplace promise</div><strong>(?P<service>.*?)</strong>',
    re.DOTALL,
)
_DELIVER_BY_RE = re.compile(r"Deliver by:\s*(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})")
_DELIVERED_BADGE_RE = re.compile(r'<span class="badge (?P<classes>[^"]*)">Delivered</span>')
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _clean_fbm_journey_html(html: str) -> str:
    value = str(html or "")
    for old, new in _JOURNEY_LABEL_REPLACEMENTS:
        value = value.replace(old, new)
    return value


def _inject_once(html: str, marker: str, payload: str, closing: str) -> str:
    value = str(html or "")
    if marker in value:
        return value
    return value.replace(closing, payload + closing, 1) if closing in value else value + payload


def _align_fbm_tracking_link_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmTrackingLinkAlignment"', _TRACKING_LINK_STYLE, '</head>')


def _align_fbm_marketplace_badge_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmMarketplaceBadgeAlignment"', _MARKETPLACE_BADGE_STYLE, '</head>')


def _align_fbm_promise_journey_html(html: str) -> str:
    return _inject_once(html, 'id="bt38FbmPromiseJourneyAlignment"', _PROMISE_JOURNEY_SCRIPT, '</body>')


def _align_fbm_event_session_refresh_html(html: str) -> str:
    """Reuse the existing shared marketplace event to refresh this FBM session from DB."""
    return _inject_once(html, 'id="bt38FbmEventSessionRefreshAlignment"', _EVENT_SESSION_REFRESH_SCRIPT, '</body>')


def _align_fbm_scroll_position_html(html: str) -> str:
    """Prevent a stale pager anchor from forcing a browser reload to the page bottom."""
    return _inject_once(html, 'id="bt38FbmScrollPositionAlignment"', _SCROLL_POSITION_SCRIPT, '</body>')


def _align_fbm_buyer_messages_card(html: str) -> str:
    value = str(html or "")
    pattern = re.compile(r'<div class="fbm-period-card(?P<class_suffix>[^"]*)" tabindex="0"><div class="fbm-period-label">Mapping review</div><div class="fbm-period-value">[^<]*</div><div class="fbm-period-tip" role="tooltip">.*?</div></div>', re.DOTALL)
    replacement = ('<div class="fbm-period-card\\g<class_suffix>" tabindex="0"><div class="fbm-period-label">Buyer messages</div><div class="fbm-period-value">0</div><div class="fbm-period-tip" role="tooltip"><div>No buyer messages are currently ingested into BT38.</div></div></div>')
    return pattern.sub(replacement, value, count=1)


def _align_fbm_recommended_shipping_html(html: str) -> str:
    """Replace generic route-capability badges with one truthful recommendation action.

    The old Marketplace / Packlink / carrier / Manual badges described available
    routes, not a proven choice for this order. The FBM row now preserves the
    marketplace promise and exposes the existing Shipping options action as the
    place where a recommendation is resolved. No carrier is called or guessed on
    page render; saved rates and user-confirmed cutoff truth remain the only valid
    inputs for a later recommendation.
    """
    value = str(html or "")

    def replace_row(match: re.Match[str]) -> str:
        row_id = int(match.group("row_id"))
        body = match.group("body")
        cell_match = _SHIPPING_CELL_RE.search(body)
        if cell_match is None:
            return match.group(0)

        old_cell_body = cell_match.group("body")
        promise_match = _MARKETPLACE_PROMISE_SERVICE_RE.search(old_cell_body)
        if promise_match is not None:
            promise_html = (
                '<div class="small text-muted">Marketplace promise</div>'
                f'<strong>{promise_match.group("service")}</strong>'
            )
        else:
            promise_html = (
                '<div class="small text-muted">Marketplace promise</div>'
                '<strong class="text-muted">Pending</strong>'
            )

        recommendation_html = (
            '<div class="small text-muted mt-2">Recommended shipping</div>'
            f'<button class="btn btn-sm btn-outline-primary fbm-shipping-options mt-1" type="button" data-order-id="{row_id}">Recommended shipping</button>'
            '<div class="fbm-row-note text-muted">Uses saved eligible rates and a user-confirmed cutoff. BT38 never guesses a cutoff time.</div>'
        )
        replacement = '<td class="fbm-route-cell">' + promise_html + recommendation_html + '</td>'
        body = body[:cell_match.start()] + replacement + body[cell_match.end():]
        return match.group(1) + body + match.group(4)

    return _FBM_ROW_RE.sub(replace_row, value)


def _delivery_evidence_by_order_row(order_row_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Read the latest persisted courier delivery timestamp for each displayed order."""
    if not order_row_ids:
        return {}

    from extensions import db
    from fbm_models import FBMShipment
    from models import MarketplaceOrder

    displayed_rows = (
        db.session.query(
            MarketplaceOrder.id,
            MarketplaceOrder.store_id,
            MarketplaceOrder.marketplace_order_id,
            MarketplaceOrder.created_at,
        )
        .filter(MarketplaceOrder.id.in_(sorted(order_row_ids)))
        .all()
    )
    identity_by_row_id = {
        int(row.id): (int(row.store_id), str(row.marketplace_order_id), row.created_at)
        for row in displayed_rows
        if row.id is not None and row.store_id is not None and row.marketplace_order_id
    }
    identities = sorted({(store_id, order_id) for store_id, order_id, _ in identity_by_row_id.values()})
    if not identities:
        return {}

    shipment_rows = (
        db.session.query(
            FBMShipment.store_id,
            FBMShipment.marketplace_order_id,
            FBMShipment.delivered_at,
            FBMShipment.id,
        )
        .filter(tuple_(FBMShipment.store_id, FBMShipment.marketplace_order_id).in_(identities))
        .order_by(FBMShipment.id.desc())
        .all()
    )
    latest_by_identity: dict[tuple[int, str], Any] = {}
    for row in shipment_rows:
        identity = (int(row.store_id), str(row.marketplace_order_id))
        if identity not in latest_by_identity:
            latest_by_identity[identity] = row.delivered_at

    return {
        row_id: {
            "created_at": created_at,
            "delivered_at": latest_by_identity.get((store_id, order_id)),
        }
        for row_id, (store_id, order_id, created_at) in identity_by_row_id.items()
    }


def _promise_date_from_row(body: str, created_at: datetime | None) -> date | None:
    """Resolve the marketplace promise date already rendered by the FBM page."""
    match = _DELIVER_BY_RE.search(body)
    if match is None:
        return None
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    try:
        day = int(match.group("day"))
        anchor = (created_at or datetime.utcnow()).date()
        due = date(anchor.year, month, day)
        if due < anchor:
            due = date(anchor.year + 1, month, day)
        return due
    except (TypeError, ValueError):
        return None


def _enrich_fbm_delivery_timing_html(html: str, *, today: date | None = None) -> str:
    """Show delivery outcome from persisted courier truth versus marketplace promise.

    Courier/provider delivery evidence controls whether delivery occurred.
    The marketplace promise controls whether that proven delivery was on time.
    No delivery timestamp or outcome is invented from tracking alone.
    """
    value = str(html or "")
    row_ids = {int(match.group("row_id")) for match in _FBM_ROW_RE.finditer(value)}
    evidence_by_row = _delivery_evidence_by_order_row(row_ids)
    if not evidence_by_row:
        return value
    today = today or datetime.utcnow().date()

    def replace_row(match: re.Match[str]) -> str:
        row_id = int(match.group("row_id"))
        body = match.group("body")
        evidence = evidence_by_row.get(row_id) or {}
        delivered_at = evidence.get("delivered_at")
        due = _promise_date_from_row(body, evidence.get("created_at"))
        badge_match = _DELIVERED_BADGE_RE.search(body)
        if badge_match is None:
            return match.group(0)

        if delivered_at is not None and due is not None:
            delivered_date = delivered_at.date() if hasattr(delivered_at, "date") else None
            if delivered_date is not None and delivered_date > due:
                replacement = '<span class="badge bg-danger">Delivered late</span>'
            else:
                replacement = '<span class="badge bg-success">Delivered</span><span class="badge bg-success bt38-on-time-badge">On time</span>'
            body = body[:badge_match.start()] + replacement + body[badge_match.end():]
        elif delivered_at is not None:
            replacement = '<span class="badge bg-primary">Delivered</span>'
            body = body[:badge_match.start()] + replacement + body[badge_match.end():]
        elif due is not None and today > due:
            delayed_badge = '<span class="badge bg-danger bt38-delayed-badge">Delayed</span>'
            if delayed_badge not in body:
                body = body[:badge_match.end()] + delayed_badge + body[badge_match.end():]

        return match.group(1) + body + match.group(4)

    return _FBM_ROW_RE.sub(replace_row, value)


def _sale_identity(record: dict[str, Any]) -> tuple[int, str] | None:
    """Retained boundary marker from the proven clarity implementation."""
    if str(record.get("log_type") or "") != "marketplace_sale":
        return None
    event_key = str(record.get("event_key") or "")
    parts = event_key.split(":", 3)
    if len(parts) < 4 or parts[0] != "order":
        return None
    try:
        store_id = int(parts[1])
    except (TypeError, ValueError):
        return None
    order_id = str(parts[2] or "").strip()
    return (store_id, order_id) if order_id else None


def install_governed_order_clarity_alignment(app) -> None:
    if getattr(app, "_bt38_order_clarity_alignment_installed", False):
        return
    from services.governed_fbm_lifecycle_alignment import install_governed_fbm_lifecycle_alignment
    from services.governed_fbm_marketplace_dispatch_authority_alignment import install_governed_fbm_marketplace_dispatch_authority_alignment
    from services.governed_fbm_fulfillment_guard import install_governed_fbm_fulfillment_guard
    from services.fbm_db_delivery_promise_alignment import install_fbm_db_delivery_promise_alignment
    from services.governed_fbm_global_search_alignment import install_governed_fbm_global_search_alignment
    from services.governed_fbm_all_orders_health_alignment import install_governed_fbm_all_orders_health_alignment
    from services.governed_fbm_overdue_alert_alignment import install_governed_fbm_overdue_alert_alignment

    install_fbm_db_delivery_promise_alignment(app)
    install_governed_fbm_global_search_alignment(app)
    install_governed_fbm_all_orders_health_alignment(app)
    install_governed_fbm_overdue_alert_alignment(app)
    install_governed_fbm_lifecycle_alignment(app)
    install_governed_fbm_marketplace_dispatch_authority_alignment()
    install_governed_fbm_fulfillment_guard(app)
    app._bt38_order_clarity_alignment_installed = True

    @app.after_request
    def bt38_order_clarity_response(response):
        path = request.path.rstrip("/") or "/"

        # Render-only marketplace boundary: persisted DB evidence only; never
        # recover/reconcile/hydrate/call a marketplace or carrier from page GET.
        if path == "/fbm" and response.status_code == 200 and response.content_type and "text/html" in response.content_type:
            html = _clean_fbm_journey_html(response.get_data(as_text=True))
            html = _align_fbm_recommended_shipping_html(html)
            html = _enrich_fbm_delivery_timing_html(html)
            html = _align_fbm_tracking_link_html(html)
            html = _align_fbm_marketplace_badge_html(html)
            html = _align_fbm_buyer_messages_card(html)
            html = _align_fbm_promise_journey_html(html)
            html = _align_fbm_event_session_refresh_html(html)
            html = _align_fbm_scroll_position_html(html)
            response.set_data(html)
        return response

    app.logger.info("BT38 order clarity alignment installed: persisted delivery promises + truthful recommended-shipping action without generic route claims + persisted courier delivery timing (On time / Delivered late / Delayed) + global persisted FBM search + all-orders persisted FBM health + low-pressure overdue alert/filter + buyer-messages health slot + clean tracking controls + sharper existing marketplace badges + DB-row-authoritative promise journey + marketplace-dispatch shipment authority + existing-event FBM session refresh + stable reload scroll position; event-persisted state remains authoritative")
