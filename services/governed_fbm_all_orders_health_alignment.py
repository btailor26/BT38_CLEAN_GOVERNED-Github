"""Align FBM health and history to the governed browser-session model.

Default FBM scope is the last 7 days. Users can explicitly widen that scope to
30/90 days, one year, or an arbitrary custom date range; that explicit action is
allowed to read the persisted order history. Orders are never removed from BT38
history merely because they fall outside the current view.

The selected history window is loaded once for the request and then browser-side
pagination owns presentation. Health cards describe the selected date window,
not just the currently visible page. No marketplace/provider calls or writes
occur here.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from flask import g, request
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from governed_fbm_routes import _platform
from models import MarketplaceOrder
from services.fbm_shipping_state import shipment_confirmation_state


_RANGE_DAYS = {
    "7d": (7, "Last 7 days"),
    "30d": (30, "Last 30 days"),
    "90d": (90, "Last 90 days"),
    "1y": (365, "Last 1 year"),
}


def _parse_day(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _selected_history_window() -> tuple[str, datetime, datetime, str, str, str]:
    """Return the explicit persisted-order window; default is seven days."""
    mode = str(request.args.get("fbm_range") or "7d").strip().lower()
    now = datetime.utcnow()

    if mode == "custom":
        raw_from = str(request.args.get("fbm_from") or "").strip()
        raw_to = str(request.args.get("fbm_to") or "").strip()
        start_at = _parse_day(raw_from)
        end_day = _parse_day(raw_to)
        if start_at is not None and end_day is not None:
            if start_at > end_day:
                start_at, end_day = end_day, start_at
                raw_from, raw_to = raw_to, raw_from
            end_at = end_day + timedelta(days=1)
            return mode, start_at, end_at, f"{start_at.strftime('%d %b %Y')} – {end_day.strftime('%d %b %Y')}", raw_from, raw_to
        mode = "7d"

    days, label = _RANGE_DAYS.get(mode, _RANGE_DAYS["7d"])
    if mode not in _RANGE_DAYS:
        mode = "7d"
    return mode, now - timedelta(days=days), now + timedelta(seconds=1), label, "", ""


def install_governed_fbm_all_orders_health_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_all_orders_health_alignment_installed", False):
        return

    from services import governed_fbm_global_search_alignment as global_search
    from services import governed_fbm_page_alignment as page_alignment

    original_health_html = page_alignment._health_html
    original_guide_html = page_alignment._guide_html

    def selected_range_snapshot_rows() -> tuple[list[MarketplaceOrder], bool]:
        """Read the selected persisted history window once for this request.

        There is deliberately no newest-N history ceiling here. The date window
        is the bound. Default 7-day reads stay narrow; wider history is queried
        only when the user explicitly asks for it.
        """
        cached = getattr(g, "_bt38_fbm_session_rows", None)
        if cached is not None:
            return list(cached), False

        _mode, start_at, end_at, _label, _raw_from, _raw_to = _selected_history_window()
        eligible = (
            func.upper(func.coalesce(MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")),
            ~func.lower(func.coalesce(MarketplaceOrder.status, "")).like("mcf_%"),
        )
        candidates = (
            db.session.query(MarketplaceOrder)
            .filter(
                *eligible,
                MarketplaceOrder.store_id.isnot(None),
                MarketplaceOrder.marketplace_order_id.isnot(None),
                MarketplaceOrder.created_at >= start_at,
                MarketplaceOrder.created_at < end_at,
            )
            .options(joinedload(MarketplaceOrder.store), joinedload(MarketplaceOrder.warehouse_stock))
            .order_by(MarketplaceOrder.id.desc())
            .all()
        )

        canonical = global_search._canonical_order_rows(candidates)
        profiles = page_alignment._profile_map([
            row for row in canonical if _platform(row).strip().lower() == "amazon"
        ])
        rows: list[MarketplaceOrder] = []
        for row in canonical:
            key = (int(row.store_id), str(row.marketplace_order_id))
            profile = profiles.get(key) if _platform(row).strip().lower() == "amazon" else None
            if page_alignment._workspace_fbm_eligible(row, profile):
                rows.append(row)

        g._bt38_fbm_session_rows = rows
        g._bt38_fbm_session_truncated = False
        g._bt38_fbm_history_window = {
            "mode": _mode,
            "start_at": start_at,
            "end_at": end_at,
            "label": _label,
            "from": _raw_from,
            "to": _raw_to,
        }
        return list(rows), False

    # Replace the later newest-N snapshot cap with the selected date window.
    # The default remains narrow (7 days); months/years are explicit user reads.
    global_search._session_snapshot_rows = selected_range_snapshot_rows

    def session_health_summary() -> dict:
        rows, _truncated = global_search._session_snapshot_rows()
        mode, start_at, end_at, label, raw_from, raw_to = _selected_history_window()

        profiles = page_alignment._profile_map([
            row for row in rows if _platform(row).strip().lower() == "amazon"
        ])
        order_rows = []
        for row in rows:
            key = (int(row.store_id), str(row.marketplace_order_id))
            profile = profiles.get(key) if _platform(row).strip().lower() == "amazon" else None
            if page_alignment._workspace_fbm_eligible(row, profile):
                order_rows.append((row, profile))

        shipments = page_alignment._shipment_map([row for row, _ in order_rows])
        dispatch_due = dispatched = awaiting = overdue = mapping_review = 0
        returns = replacements = refund_issues = 0
        platform_counts = {}

        for row, _profile in order_rows:
            platform = _platform(row).strip() or "Other"
            platform_counts[platform] = platform_counts.get(platform, 0) + 1
            shipment = shipments.get((int(row.store_id), str(row.marketplace_order_id)))
            queue = global_search.workflow_queue_for(row, shipment)
            if queue == "ready_dispatch":
                dispatch_due += 1
            elif queue == "dispatched":
                dispatched += 1
            elif queue == "replacements":
                replacements += 1
            elif queue == "refunds":
                refund_issues += 1

            if shipment:
                state = shipment_confirmation_state(shipment)
                if state == "awaiting_carrier_acceptance":
                    awaiting += 1
                elif state == "acceptance_overdue":
                    overdue += 1

                if platform.casefold() == "amazon":
                    review = getattr(shipment, "mapping_review", None)
                    if review is not None and getattr(review, "status", None) == "under_review":
                        mapping_review += 1

            status = str(getattr(row, "status", "") or "").strip().lower()
            if status in {"return_requested", "returned"}:
                returns += 1

        total = len(order_rows)
        risk_actions = overdue + returns + replacements + refund_issues
        health_base = max(1, total + returns)
        health_score = max(0, min(100, round(100 * (health_base - risk_actions) / health_base)))
        return {
            "period_mode": mode,
            "period_label": label,
            "period_start": start_at,
            "period_end": end_at,
            "range_from": raw_from,
            "range_to": raw_to,
            "total": total,
            "ready": dispatch_due,
            "dispatch_due": dispatch_due,
            "dispatched": dispatched,
            "awaiting_acceptance": awaiting,
            "overdue": overdue,
            "mapping_review": mapping_review,
            "returns": returns,
            "replacements": replacements,
            "refund_issues": refund_issues,
            "platform_counts": dict(sorted(platform_counts.items(), key=lambda item: (-item[1], item[0].lower()))),
            "health_score": health_score,
            "risk_actions": risk_actions,
            "shipping_actions": dispatch_due,
            "truncated": False,
        }

    def operational_controls(health: dict) -> str:
        mode = str(health.get("period_mode") or "7d")
        raw_from = str(health.get("range_from") or "")
        raw_to = str(health.get("range_to") or "")
        preserved = []
        for name in ("platform", "status", "search", "q"):
            value = str(request.args.get(name) or "").strip()
            if value:
                preserved.append(
                    f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'
                )
        options = []
        for value, text in (("7d", "7 days"), ("30d", "30 days"), ("90d", "90 days"), ("1y", "1 year"), ("custom", "Custom")):
            selected = " selected" if mode == value else ""
            options.append(f'<option value="{value}"{selected}>{text}</option>')
        return (
            '<form id="bt38FbmHistoryControls" class="fbm-period-controls" method="get" action="/fbm" aria-label="FBM order history controls">'
            + "".join(preserved)
            + '<label class="small text-muted" for="bt38FbmRangeSelect">Orders</label>'
            + '<select id="bt38FbmRangeSelect" class="form-select form-select-sm" name="fbm_range" style="width:auto" '
              'onchange="if(this.value!==\'custom\'){this.form.submit()}">' + "".join(options) + '</select>'
            + f'<input class="form-control form-control-sm" style="width:145px" type="date" name="fbm_from" value="{escape(raw_from)}" aria-label="FBM from date">'
            + f'<input class="form-control form-control-sm" style="width:145px" type="date" name="fbm_to" value="{escape(raw_to)}" aria-label="FBM to date">'
            + '<button class="btn btn-sm btn-outline-primary" type="submit">Apply</button>'
            + '<span class="small text-muted ms-1">Show</span>'
            + '<select id="bt38ResultsPerPageSelect" class="form-select form-select-sm" style="width:auto" aria-label="FBM orders per page">'
              '<option value="15">15</option><option value="30">30</option><option value="50">50</option><option value="100">100</option></select>'
            + '</form>'
        )

    def operational_health_html(health: dict) -> str:
        html = original_health_html(health)
        mapping_card = page_alignment._metric_card(
            "Mapping review",
            int(health.get("mapping_review", 0) or 0),
            [f"{int(health.get('mapping_review', 0) or 0)} carrier mappings need review"],
        )
        return html.replace(mapping_card, "")

    def operational_guide_html(health: dict) -> str:
        return original_guide_html(health).replace(
            "Ready-to-ship, overdue carrier and mapping actions drive this number.",
            "Current Ready-to-dispatch orders drive this number; carrier risks are shown separately.",
        )

    page_alignment._health_summary = session_health_summary
    page_alignment._period_controls = operational_controls
    page_alignment._health_html = operational_health_html
    page_alignment._guide_html = operational_guide_html
    app._bt38_fbm_all_orders_health_alignment_installed = True
    app.logger.info(
        "BT38 FBM history aligned: 7-day default; explicit 30/90/day/year/custom history reads; history never dropped by newest-N cap; health follows selected date range"
    )
