"""Align FBM history, health and page-size controls to the governed page model.

The selected history window defaults to three days. Wider ranges are loaded only
when the user explicitly selects them. Health and workflow counts derive from the
complete selected-history FBM snapshot, while the ordinary order-table read stays
bounded to the selected 15/30/50/100 presentation size.

The persisted MarketplaceOrder.created_at column is the single timestamp truth
for history membership. Range instructions are interpreted as Europe/London
calendar days and converted to naive UTC boundaries for the database query.

No marketplace/provider calls or writes occur here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from flask import g, request, session
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from governed_fbm_routes import _platform
from models import MarketplaceOrder
from services.fbm_shipping_state import shipment_confirmation_state


_RANGE_DAYS = {
    "3d": (3, "Last 3 days"),
    "7d": (7, "Last 7 days"),
    "30d": (30, "Last 30 days"),
    "90d": (90, "Last 90 days"),
    "1y": (365, "Last 1 year"),
}
_PAGE_SIZES = (15, 30, 50, 100)
_TZ = ZoneInfo("Europe/London")


def _parse_day(value: str):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _utc_db_boundary(day) -> datetime:
    """Convert a Europe/London calendar-day boundary to naive UTC for DB truth."""
    local = datetime(day.year, day.month, day.day, tzinfo=_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _selected_history_window() -> tuple[str, datetime, datetime, str, str, str]:
    """Return the instructed calendar-day window over persisted DB created_at."""
    mode = str(request.args.get("fbm_range") or "3d").strip().lower()
    today = datetime.now(_TZ).date()

    if mode == "custom":
        raw_from = str(request.args.get("fbm_from") or "").strip()
        raw_to = str(request.args.get("fbm_to") or "").strip()
        start_day = _parse_day(raw_from)
        end_day = _parse_day(raw_to)
        if start_day is not None and end_day is not None:
            if start_day > end_day:
                start_day, end_day = end_day, start_day
                raw_from, raw_to = raw_to, raw_from
            start_at = _utc_db_boundary(start_day)
            end_at = _utc_db_boundary(end_day + timedelta(days=1))
            return (
                mode,
                start_at,
                end_at,
                f"{start_day.strftime('%d %b %Y')} – {end_day.strftime('%d %b %Y')}",
                raw_from,
                raw_to,
            )
        mode = "3d"

    days, label = _RANGE_DAYS.get(mode, _RANGE_DAYS["3d"])
    if mode not in _RANGE_DAYS:
        mode = "3d"
        days, label = _RANGE_DAYS["3d"]
    start_day = today - timedelta(days=days - 1)
    start_at = _utc_db_boundary(start_day)
    end_at = _utc_db_boundary(today + timedelta(days=1))
    return mode, start_at, end_at, label, "", ""


def _persisted_page_size() -> int:
    """Keep the user's 15/30/50/100 presentation choice for the browser session."""
    requested = str(request.args.get("limit") or "").strip()
    if requested:
        try:
            parsed = int(requested)
        except (TypeError, ValueError):
            parsed = 15
        value = parsed if parsed in _PAGE_SIZES else 15
        session["bt38_fbm_page_size"] = value
        return value

    try:
        stored = int(session.get("bt38_fbm_page_size", 15) or 15)
    except (TypeError, ValueError):
        stored = 15
    return stored if stored in _PAGE_SIZES else 15


def install_governed_fbm_all_orders_health_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_all_orders_health_alignment_installed", False):
        return

    from services import governed_fbm_global_search_alignment as global_search
    from services import governed_fbm_page_alignment as page_alignment

    original_health_html = page_alignment._health_html
    original_guide_html = page_alignment._guide_html

    def _selected_fbm_rows() -> list[MarketplaceOrder]:
        """Complete canonical eligible FBM snapshot for health/workflow truth only."""
        cached = getattr(g, "_bt38_fbm_health_rows", None)
        if cached is not None:
            return list(cached)

        mode, start_at, end_at, label, raw_from, raw_to = _selected_history_window()
        candidates = (
            db.session.query(MarketplaceOrder)
            .filter(
                func.upper(func.coalesce(MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")),
                ~func.lower(func.coalesce(MarketplaceOrder.status, "")).like("mcf_%"),
                MarketplaceOrder.store_id.isnot(None),
                MarketplaceOrder.marketplace_order_id.isnot(None),
                MarketplaceOrder.created_at >= start_at,
                MarketplaceOrder.created_at < end_at,
            )
            .options(joinedload(MarketplaceOrder.store))
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

        g._bt38_fbm_health_rows = rows
        g._bt38_fbm_history_window = {
            "mode": mode,
            "start_at": start_at,
            "end_at": end_at,
            "label": label,
            "from": raw_from,
            "to": raw_to,
        }
        return list(rows)

    def _selected_shipment_map(rows: list[MarketplaceOrder]) -> dict:
        """Load shipment truth once for the complete health/workflow working set."""
        cached = getattr(g, "_bt38_fbm_selected_shipment_map", None)
        if cached is not None:
            return cached
        shipments = page_alignment._shipment_map(rows)
        g._bt38_fbm_selected_shipment_map = shipments
        return shipments

    def _health_rows() -> list[MarketplaceOrder]:
        return _selected_fbm_rows()

    def selected_range_workflow_snapshot() -> dict:
        """Classify tab counts from complete history without making it the page row set."""
        cached = getattr(g, "_bt38_fbm_workflow_snapshot", None)
        if cached is not None:
            return cached

        rows = _selected_fbm_rows()
        shipments = _selected_shipment_map(rows)
        grouped = {name: [] for name in global_search._WORKFLOW_TABS}
        for row in rows:
            shipment = shipments.get((int(row.store_id), str(row.marketplace_order_id)))
            queue = global_search.workflow_queue_for(row, shipment)
            if queue in grouped:
                grouped[queue].append(row)

        snapshot = {
            "rows": grouped,
            "counts": {name: len(grouped[name]) for name in global_search._WORKFLOW_TABS},
            "truncated": False,
        }
        g._bt38_fbm_workflow_snapshot = snapshot
        return snapshot

    # Keep global_search._session_snapshot_rows as the existing bounded page/search
    # authority. Only workflow/health require the complete selected-history snapshot.
    global_search._persisted_workflow_snapshot = selected_range_workflow_snapshot
    page_alignment._requested_limit = _persisted_page_size

    def session_health_summary() -> dict:
        rows = _selected_fbm_rows()
        mode, start_at, end_at, label, raw_from, raw_to = _selected_history_window()
        shipments = _selected_shipment_map(rows)
        workflow = selected_range_workflow_snapshot()
        workflow_counts = workflow["counts"]
        dispatch_due = int(workflow_counts.get("ready_dispatch", 0) or 0)
        dispatched = int(workflow_counts.get("dispatched", 0) or 0)
        replacements = int(workflow_counts.get("replacements", 0) or 0)
        refund_issues = int(workflow_counts.get("refunds", 0) or 0)
        awaiting = overdue = mapping_review = 0
        returns = 0
        platform_counts: dict[str, int] = {}

        # Workflow classification is already complete and request-cached above.
        # This pass only derives metrics that are not represented by workflow tabs.
        for row in rows:
            platform = _platform(row).strip() or "Other"
            platform_counts[platform] = platform_counts.get(platform, 0) + 1
            shipment = shipments.get((int(row.store_id), str(row.marketplace_order_id)))

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

        total = len(rows)
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
        """Render the single authoritative FBM history form."""
        mode = str(health.get("period_mode") or "3d")
        raw_from = str(health.get("range_from") or "")
        raw_to = str(health.get("range_to") or "")
        page_size = _persisted_page_size()
        preserved = []
        for name in ("platform", "status", "search", "q", "fbm_tab"):
            value = str(request.args.get(name) or "").strip()
            if value:
                preserved.append(f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">')
        options = []
        for value, text in (("3d", "3 days"), ("7d", "7 days"), ("30d", "30 days"), ("90d", "90 days"), ("1y", "1 year"), ("custom", "Custom")):
            selected = " selected" if mode == value else ""
            options.append(f'<option value="{value}"{selected}>{text}</option>')
        size_options = []
        for value in _PAGE_SIZES:
            selected = " selected" if page_size == value else ""
            size_options.append(f'<option value="{value}"{selected}>{value}</option>')
        return (
            '<form id="bt38FbmHistoryControls" class="fbm-period-controls" method="get" action="/fbm" aria-label="FBM order history controls">'
            + "".join(preserved)
            + '<label class="small text-muted" for="bt38FbmRangeSelect">Orders</label>'
            + '<select id="bt38FbmRangeSelect" class="form-select form-select-sm" name="fbm_range" style="width:auto">' + "".join(options) + '</select>'
            + f'<input class="form-control form-control-sm" style="width:145px" type="date" name="fbm_from" value="{escape(raw_from)}" aria-label="FBM from date">'
            + f'<input class="form-control form-control-sm" style="width:145px" type="date" name="fbm_to" value="{escape(raw_to)}" aria-label="FBM to date">'
            + '<button class="btn btn-sm btn-outline-primary" type="submit">Apply</button>'
            + '<span class="small text-muted ms-1">Show</span>'
            + '<select id="bt38ResultsPerPageSelect" class="form-select form-select-sm" name="limit" style="width:auto" aria-label="FBM orders per page">'
            + "".join(size_options)
            + '</select>'
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
        "BT38 FBM history aligned: bounded ordinary page working set; complete selected-history health/workflow truth; one URL-request history authority; no marketplace/provider reads"
    )
