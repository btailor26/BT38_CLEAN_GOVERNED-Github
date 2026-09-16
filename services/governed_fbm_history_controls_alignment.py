"""Wire FBM history controls to one server-backed governed order reader.

Presentation/read alignment only: no marketplace/provider read, worker, poller,
writer or inventory path. History/search/page-size changes are explicit user
events; lifecycle tabs stay inside the existing browser-session controller.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from flask import g, request

import services.governed_fbm_global_search_alignment as controls
import services.governed_fbm_page_alignment as page
import services.governed_fbm_all_orders_health_alignment as health_alignment


_TZ = ZoneInfo("Europe/London")

# One history vocabulary everywhere. Three days is the default for a fresh FBM
# request; wider history is always explicit.
controls._RANGE_DAYS = {"3d": 3, "7d": 7, "30d": 30, "90d": 90, "1y": 365}
health_alignment._RANGE_DAYS = {
    "3d": (3, "Last 3 days"),
    "7d": (7, "Last 7 days"),
    "30d": (30, "Last 30 days"),
    "90d": (90, "Last 90 days"),
    "1y": (365, "Last year"),
}


def _range_key():
    if not str(request.args.get("fbm_range") or "").strip():
        return "3d"
    raw = str(request.args.get("fbm_range") or "3d").strip().lower()
    aliases = {
        "3": "3d", "3day": "3d", "3days": "3d",
        "7": "7d", "7day": "7d", "7days": "7d",
        "30": "30d", "30day": "30d", "30days": "30d",
        "90": "90d", "90day": "90d", "90days": "90d",
        "365": "1y", "year": "1y", "1year": "1y",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in {*controls._RANGE_DAYS, "custom"} else "3d"


def _parse_date(value: str):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _range_bounds():
    """One timestamp boundary authority; every invalid/missing range falls to 3d."""
    mode = _range_key()
    today = datetime.now(_TZ).date()
    if mode == "custom":
        start_date = _parse_date(request.args.get("fbm_from"))
        end_date = _parse_date(request.args.get("fbm_to"))
        if start_date is not None and end_date is not None and start_date <= end_date:
            start_local = datetime(start_date.year, start_date.month, start_date.day, tzinfo=_TZ)
            end_local = datetime(end_date.year, end_date.month, end_date.day, tzinfo=_TZ) + timedelta(days=1)
            return (
                "custom",
                start_local.astimezone(timezone.utc).replace(tzinfo=None),
                end_local.astimezone(timezone.utc).replace(tzinfo=None),
                f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}",
            )
        mode = "3d"

    days = controls._RANGE_DAYS.get(mode, 3)
    if mode not in controls._RANGE_DAYS:
        mode, days = "3d", 3
    start_date = today - timedelta(days=days - 1)
    start_local = datetime(start_date.year, start_date.month, start_date.day, tzinfo=_TZ)
    end_local = datetime(today.year, today.month, today.day, tzinfo=_TZ) + timedelta(days=1)
    labels = {
        "3d": "Last 3 days", "7d": "Last 7 days", "30d": "Last 30 days",
        "90d": "Last 90 days", "1y": "Last year",
    }
    return (
        mode,
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
        labels.get(mode, "Last 3 days"),
    )


# Replace both inherited 7-day fallbacks, not only the dropdown selection.
controls._range_key = _range_key
controls._range_bounds = _range_bounds


# Keep exactly one history/search surface beside the Data Truth Review area.
# Page size remains the existing bottom-of-page presentation control.
def _controls_html() -> str:
    mode = controls._range_key()
    term = controls._search_term()
    from_value = str(request.args.get("fbm_from") or "")
    to_value = str(request.args.get("fbm_to") or "")
    preserved = controls._query_args_without("fbm_range", "fbm_from", "fbm_to", "search", "fbm_tab")
    hidden = "".join(
        f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'
        for name, value in preserved.items()
    )
    options = "".join(
        f'<option value="{value}"{" selected" if mode == value else ""}>{label}</option>'
        for value, label in (
            ("3d", "3 days"), ("7d", "7 days"), ("30d", "30 days"),
            ("90d", "90 days"), ("1y", "Last year"), ("custom", "Custom"),
        )
    )
    clear_args = controls._query_args_without("search", "fbm_tab")
    clear_url = "/fbm" + (("?" + urlencode(clear_args)) if clear_args else "")
    return (
        '<div class="card-header border-bottom-0 pb-0">'
        '<form id="bt38FbmControls" class="d-flex gap-2 align-items-center flex-wrap" method="get" action="/fbm">'
        + hidden
        + '<label class="small text-muted mb-0">History</label>'
        + f'<select id="bt38FbmRange" class="form-select form-select-sm" style="width:auto" name="fbm_range" onchange="if(this.value!==\'custom\'){{this.form.submit();}}">{options}</select>'
        + f'<input id="bt38FbmFrom" class="form-control form-control-sm" style="width:auto" type="date" name="fbm_from" value="{escape(from_value)}" aria-label="From date">'
        + f'<input id="bt38FbmTo" class="form-control form-control-sm" style="width:auto" type="date" name="fbm_to" value="{escape(to_value)}" aria-label="To date">'
        + f'<input id="bt38FbmGlobalSearchInput" class="form-control form-control-sm" style="width:min(300px,65vw)" type="search" name="search" autocomplete="off" value="{escape(term)}" placeholder="Order, SKU, tracking, carrier or status">'
        + '<button class="btn btn-sm btn-primary" type="submit">Apply</button>'
        + f'<a id="bt38FbmGlobalSearchClear" class="btn btn-sm btn-outline-secondary" href="{escape(clear_url)}">Clear search</a>'
        + '</form>'
        + '</div>'
    )


controls._controls_html = _controls_html


# Lifecycle tabs intentionally keep the dispatch controller's existing local
# browser-session click handler. Do not replace it with a second server tab
# authority.
if not getattr(page, "_bt38_history_controls_aligned", False):
    _original_profile_map = page._profile_map
    _original_shipment_map = page._shipment_map

    def _cached_profile_map(rows):
        cache = getattr(g, "_bt38_fbm_history_profile_cache", None)
        if cache is None:
            cache = {}
            g._bt38_fbm_history_profile_cache = cache
        missing = [
            row for row in rows
            if row.store_id is not None and row.marketplace_order_id
            and (int(row.store_id), str(row.marketplace_order_id)) not in cache
        ]
        if missing:
            cache.update(_original_profile_map(missing))
        return {
            (int(row.store_id), str(row.marketplace_order_id)): cache.get((int(row.store_id), str(row.marketplace_order_id)))
            for row in rows
            if row.store_id is not None and row.marketplace_order_id
            and cache.get((int(row.store_id), str(row.marketplace_order_id))) is not None
        }

    def _cached_shipment_map(rows):
        cache = getattr(g, "_bt38_fbm_history_shipment_cache", None)
        loaded = getattr(g, "_bt38_fbm_history_shipment_keys", None)
        if cache is None:
            cache = {}
            g._bt38_fbm_history_shipment_cache = cache
        if loaded is None:
            loaded = set()
            g._bt38_fbm_history_shipment_keys = loaded
        keys = {
            (int(row.store_id), str(row.marketplace_order_id))
            for row in rows if row.store_id is not None and row.marketplace_order_id
        }
        missing_keys = keys - loaded
        if missing_keys:
            missing_rows = [
                row for row in rows
                if row.store_id is not None and row.marketplace_order_id
                and (int(row.store_id), str(row.marketplace_order_id)) in missing_keys
            ]
            fresh = _original_shipment_map(missing_rows)
            controls._prime_shipment_relationships(fresh.values())
            cache.update(fresh)
            loaded.update(missing_keys)
        return {key: cache.get(key) for key in keys if cache.get(key) is not None}

    def _selected_rows(limit: int):
        # History membership is decided first by the canonical DB timestamp
        # snapshot. Search narrows that snapshot. Page size is presentation only.
        rows, truncated = controls._session_snapshot_rows()
        term = controls._search_term()
        if term:
            rows = [row for row in rows if controls._row_matches_term(row, term)]
        visible = list(rows[:limit])
        return visible, bool(truncated or len(rows) > limit)

    page._requested_limit = health_alignment._persisted_page_size
    page._profile_map = _cached_profile_map
    page._shipment_map = _cached_shipment_map
    page._latest_distinct_fbm_rows = _selected_rows
    page._health_period = controls._range_bounds
    page._period_controls = lambda _health: ""
    page._expand_control = lambda html, *, visible_limit, has_more: html
    page._bt38_history_controls_aligned = True
