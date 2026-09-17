"""Keep FBM History, lifecycle counts and Health on one browser-session snapshot.

The initial /fbm read is explicitly bound to the canonical bounded page-reader
contract even though older dispatch alignment replaces the module attribute
before this installer runs. History/lifecycle/Health then operate over the
rendered browser-session facts. The bottom pager remains presentation-only.

No marketplace/provider read, write, polling, timer, EventSource or fetch path is
introduced by this module.
"""
from __future__ import annotations

from services import governed_fbm_dispatch_queue_alignment as dispatch
from services import governed_fbm_page_alignment as page
from services.fbm_shipping_state import shipment_confirmation_state



def _canonical_bounded_page_rows(limit: int):
    """Use the original page reader contract without the dispatch broad-read override."""
    eligible = (
        page.func.upper(page.func.coalesce(page.MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")),
        ~page.func.lower(page.func.coalesce(page.MarketplaceOrder.status, "")).like("mcf_%"),
    )
    query = page.db.session.query(page.MarketplaceOrder).filter(*eligible)
    platform_filter = str(page.request.args.get("platform") or "").strip().lower()
    status_filter = str(page.request.args.get("status") or "").strip().lower()
    if platform_filter:
        query = query.filter(page.MarketplaceOrder.store.has(platform=platform_filter))
    tracking_present = page.MarketplaceOrder.tracking_number.isnot(None) & (page.MarketplaceOrder.tracking_number != "")
    if status_filter == "tracking recorded":
        query = query.filter(tracking_present)
    elif status_filter == "dispatched":
        query = query.filter(~tracking_present, page.MarketplaceOrder.shipped_at.isnot(None))
    elif status_filter == "ready for fbm routing":
        query = query.filter(~tracking_present, page.MarketplaceOrder.shipped_at.is_(None))
    candidate_limit = min(
        page._FBM_MAX_EXPANDED * page._FBM_DISCOVERY_MULTIPLIER,
        max(limit + 1, (limit + 1) * page._FBM_DISCOVERY_MULTIPLIER),
    )
    candidates = (
        query.options(page.joinedload(page.MarketplaceOrder.store))
        .order_by(page.MarketplaceOrder.id.desc())
        .limit(candidate_limit)
        .all()
    )
    rows = []
    seen = set()
    for row in candidates:
        if row.store_id is None or not row.marketplace_order_id:
            continue
        key = (int(row.store_id), str(row.marketplace_order_id))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= limit + 1:
            break
    rows.sort(key=lambda row: (row.created_at is not None, row.created_at, row.id), reverse=True)
    has_more = len(rows) > limit or len(candidates) == candidate_limit
    return rows[:limit], has_more


def _bounded_browser_session_rows(limit: int):
    """Keep normal landing bounded, but preserve the existing explicit lifecycle loader."""
    tab = str(page.request.args.get("fbm_tab") or "").strip().lower()
    search = str(page.request.args.get("search") or "").strip()
    if tab or search:
        from services import governed_fbm_global_search_alignment as global_search
        return global_search._workflow_rows(limit) if tab else global_search._search_rows(limit)
    return page._bt38_original_bounded_fbm_rows(limit)


def _session_presentation(rows):
    payload = dispatch._bt38_original_presentation(rows)
    shipments = page._shipment_map(rows)
    for row in rows:
        info = payload.get(str(row.id))
        if info is None:
            continue
        key = (int(row.store_id), str(row.marketplace_order_id))
        shipment = shipments.get(key)
        state = shipment_confirmation_state(shipment) if shipment else ""
        mapping_review = False
        if shipment and dispatch._marketplace_platform_for(row) == "amazon":
            review = getattr(shipment, "mapping_review", None)
            mapping_review = bool(review is not None and getattr(review, "status", None) == "under_review")
        status = str(getattr(row, "status", "") or "").strip().lower()
        info.update({
            "platform": dispatch._marketplace_platform_for(row) or "other",
            "shipment_state": state,
            "mapping_review": mapping_review,
            "return_event": status in {"return_requested", "returned"},
        })
    return payload


def _browser_session_health_shell() -> dict:
    from services import governed_fbm_all_orders_health_alignment as health
    mode, start_at, end_at, label, raw_from, raw_to = health._selected_history_window()
    return {
        "period_mode": mode, "period_label": label, "period_start": start_at, "period_end": end_at,
        "range_from": raw_from, "range_to": raw_to, "total": 0, "ready": 0, "dispatch_due": 0,
        "dispatched": 0, "awaiting_acceptance": 0, "overdue": 0, "mapping_review": 0, "returns": 0,
        "replacements": 0, "refund_issues": 0, "platform_counts": {}, "health_score": 100,
        "risk_actions": 0, "shipping_actions": 0, "truncated": False, "source": "browser_session",
    }


def _session_health_script() -> str:
    """Lifecycle/History controls have one owner; do not install a competing controller."""
    return ""


def install_governed_fbm_browser_session_authority_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_browser_session_authority_alignment_installed", False):
        return

    # Dispatch alignment has already replaced the module attribute at this point.
    # Bind the browser session to the canonical bounded page contract explicitly;
    # never capture dispatch._complete_fbm_page_rows as the "bounded" reader.
    page._bt38_original_bounded_fbm_rows = _canonical_bounded_page_rows
    page._latest_distinct_fbm_rows = _bounded_browser_session_rows

    page._health_summary = _browser_session_health_shell

    if not hasattr(dispatch, "_bt38_original_presentation"):
        dispatch._bt38_original_presentation = dispatch._presentation
    dispatch._presentation = _session_presentation

    if not hasattr(dispatch, "_bt38_original_inject"):
        dispatch._bt38_original_inject = dispatch._inject
    def aligned_inject(html, payload, fba_count):
        return dispatch._bt38_original_inject(html, payload, fba_count)
    dispatch._inject = aligned_inject
    app._bt38_fbm_browser_session_authority_alignment_installed = True
    app.logger.info("BT38 FBM browser-session authority aligned: canonical bounded initial read; dispatch broad-read override bypassed; Health/lifecycle use rendered session facts; exact-record events preserved")