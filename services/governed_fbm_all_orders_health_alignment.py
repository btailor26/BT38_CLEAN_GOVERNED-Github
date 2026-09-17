"""FBM History-window helper only.

The former all-orders Health/workflow snapshot authority was retired. Health,
lifecycle and rows are owned by the active bounded browser-session path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import request

_RANGE_DAYS = {
    "3d": (3, "Last 3 days"),
    "7d": (7, "Last 7 days"),
    "30d": (30, "Last 30 days"),
    "90d": (90, "Last 90 days"),
    "1y": (365, "Last 1 year"),
}
_TZ = ZoneInfo("Europe/London")


def _parse_day(value: str):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _utc_db_boundary(day) -> datetime:
    local = datetime(day.year, day.month, day.day, tzinfo=_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _selected_history_window() -> tuple[str, datetime, datetime, str, str, str]:
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
            return (
                mode,
                _utc_db_boundary(start_day),
                _utc_db_boundary(end_day + timedelta(days=1)),
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
    return mode, _utc_db_boundary(start_day), _utc_db_boundary(today + timedelta(days=1)), label, "", ""


def install_governed_fbm_all_orders_health_alignment(app):
    """Retired compatibility shim.

    Kept only so legacy imports/tests cannot fail during collection. It installs
    no routes, readers, Health overrides, queries, polling, or session authority.
    """
    return app
