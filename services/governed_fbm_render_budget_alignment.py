"""Keep the existing FBM browser-session snapshot inside the visible-page budget.

This is alignment only. The existing governed browser-session snapshot remains
FBM read authority; ordinary /fbm opens hydrate only the visible 15 orders.
Explicit Show 15 more requests expand that same snapshot in 15-row steps. No
marketplace/provider call, polling loop, write path or background worker is
introduced here.
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from flask import g, request
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from models import MarketplaceOrder
from governed_fbm_routes import _platform

_PAGE_SIZE = 15
_MAX_EXPANDED = 300


def _visible_limit() -> int:
    try:
        requested = int(request.args.get("limit") or _PAGE_SIZE)
    except (TypeError, ValueError):
        requested = _PAGE_SIZE
    requested = max(_PAGE_SIZE, requested)
    return min(_MAX_EXPANDED, ((requested + _PAGE_SIZE - 1) // _PAGE_SIZE) * _PAGE_SIZE)


def _expand_control(html: str, *, visible_limit: int, has_more: bool) -> str:
    params = {}
    for name in ("platform", "status", "health_period", "health_date", "health_month"):
        value = str(request.args.get(name) or "").strip()
        if value:
            params[name] = value

    actions = []
    if visible_limit > _PAGE_SIZE:
        collapse = dict(params)
        collapse["limit"] = _PAGE_SIZE
        actions.append(
            f'<a class="btn btn-sm btn-outline-secondary" href="{escape(request.path)}?{urlencode(collapse)}">Show latest 15</a>'
        )
    if has_more and visible_limit < _MAX_EXPANDED:
        expand = dict(params)
        expand["limit"] = min(_MAX_EXPANDED, visible_limit + _PAGE_SIZE)
        actions.append(
            f'<a id="fbmExpandOrders" class="btn btn-sm btn-outline-primary" href="{escape(request.path)}?{urlencode(expand)}">Show 15 more</a>'
        )
    if not actions:
        return html

    control = (
        '<div class="card-footer d-flex justify-content-between align-items-center flex-wrap gap-2">'
        f'<span class="small text-muted">Showing the latest {visible_limit} FBM orders. Older orders load only when expanded.</span>'
        f'<div class="d-flex gap-2">{"".join(actions)}</div></div>'
    )
    marker = "</tbody></table></div>\n</div>"
    if marker not in html:
        return html
    return html.replace(marker, f"</tbody></table></div>\n{control}\n</div>", 1)


def install_governed_fbm_render_budget_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_render_budget_alignment_installed", False):
        return

    from services import governed_fbm_global_search_alignment as session_alignment
    from services import governed_fbm_page_alignment as page_alignment

    def visible_session_snapshot_rows():
        cached = getattr(g, "_bt38_fbm_session_rows", None)
        if cached is not None:
            return list(cached), bool(getattr(g, "_bt38_fbm_session_truncated", False))

        limit = _visible_limit()
        eligible = (
            func.upper(func.coalesce(MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")),
            ~func.lower(func.coalesce(MarketplaceOrder.status, "")).like("mcf_%"),
        )
        candidate_limit = min((_MAX_EXPANDED * 4) + 1, ((limit + 1) * 4) + 1)
        candidates = (
            db.session.query(MarketplaceOrder)
            .filter(*eligible)
            .filter(MarketplaceOrder.store_id.isnot(None), MarketplaceOrder.marketplace_order_id.isnot(None))
            .options(joinedload(MarketplaceOrder.store), joinedload(MarketplaceOrder.warehouse_stock))
            .order_by(MarketplaceOrder.id.desc())
            .limit(candidate_limit)
            .all()
        )
        canonical = session_alignment._canonical_order_rows(candidates)
        candidate_truncated = len(candidates) >= candidate_limit
        canonical_truncated = len(canonical) > limit
        canonical = canonical[: limit + 1]

        profiles = page_alignment._profile_map([
            row for row in canonical if _platform(row).strip().lower() == "amazon"
        ])
        rows = []
        for row in canonical:
            key = (int(row.store_id), str(row.marketplace_order_id))
            profile = profiles.get(key) if _platform(row).strip().lower() == "amazon" else None
            if page_alignment._workspace_fbm_eligible(row, profile):
                rows.append(row)

        has_more = candidate_truncated or canonical_truncated or len(rows) > limit
        rows = rows[:limit]
        g._bt38_fbm_session_rows = rows
        g._bt38_fbm_session_truncated = has_more
        return list(rows), has_more

    session_alignment._session_snapshot_rows = visible_session_snapshot_rows
    page_alignment._expand_control = _expand_control

    app._bt38_fbm_render_budget_alignment_installed = True
    app.logger.info(
        "BT38 FBM render budget aligned: 15-row session snapshot by default; explicit 15-row expansion only; no marketplace/provider page reads"
    )
