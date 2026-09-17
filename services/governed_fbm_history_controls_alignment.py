"""Wire FBM History controls without replacing the bounded /fbm row reader.

History is browser-session presentation state. The initial /fbm navigation stays
owned by governed_fbm_page_alignment._latest_distinct_fbm_rows so it cannot be
expanded by the older server-backed History snapshot path.

No marketplace/provider read, writer, poller, timer or parallel event path is
introduced here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import g, request

import services.governed_fbm_global_search_alignment as controls
import services.governed_fbm_page_alignment as page
import services.governed_fbm_all_orders_health_alignment as health_alignment


_TZ = ZoneInfo("Europe/London")

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


controls._range_key = _range_key
controls._range_bounds = _range_bounds


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

    # Keep profile/shipment request-local caches, but DO NOT replace
    # page._latest_distinct_fbm_rows. The original bounded reader remains the
    # initial /fbm authority and the browser controller owns History filtering.
    page._profile_map = _cached_profile_map
    page._shipment_map = _cached_shipment_map
    page._health_period = controls._range_bounds
    page._period_controls = lambda _health: ""
    page._bt38_history_controls_aligned = True
