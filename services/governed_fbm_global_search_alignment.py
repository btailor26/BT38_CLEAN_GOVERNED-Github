"""Align FBM reads to the existing BT38 browser-session architecture.

The page uses explicit user-selected history windows and page sizes. Normal page
rendering never calls a marketplace/provider and never writes orders, shipments
or inventory. Search/date/page-size changes are native GET requests so the
controls work without depending on JavaScript event wiring.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from flask import g, request
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import set_committed_value

from extensions import db
from fbm_models import FBMProviderCase, FBMShipmentMappingReview
from models import MarketplaceOrder
from governed_fbm_routes import _platform


_MAX_SEARCH_LENGTH = 200
_PAGE_SIZES = (15, 30, 50, 100)
_RANGE_DAYS = {"3d": 3, "7d": 7, "30d": 30, "90d": 90, "1y": 365}
_RANGE_ROW_CAP = 5000
_RANGE_CANDIDATE_MULTIPLIER = 4
_TZ = ZoneInfo("Europe/London")
_CANCELLED_STATUSES = {"cancelled", "canceled", "cancelled_by_buyer", "cancelled_by_seller"}
_REPLACEMENT_TERMS = ("replacement", "replaced")
_REFUND_TERMS = ("refund", "refunded", "return", "returned", "inr", "case", "claim", "dispute", "issue")
_DISPATCHED_STATUS_TERMS = ("shipped", "dispatched", "delivered", "fulfilled", "completed")
_WORKFLOW_TABS = {"ready_dispatch", "dispatched", "sds", "replacements", "refunds"}


def _search_term() -> str:
    return str(request.args.get("search") or request.args.get("q") or "").strip()[:_MAX_SEARCH_LENGTH]


def _page_size() -> int:
    try:
        value = int(request.args.get("limit") or 15)
    except (TypeError, ValueError):
        value = 15
    return value if value in _PAGE_SIZES else 15


def _range_key() -> str:
    raw = str(request.args.get("fbm_range") or "3d").strip().lower()
    aliases = {
        "3": "3d", "3day": "3d", "3days": "3d",
        "7": "7d", "7day": "7d", "7days": "7d",
        "30": "30d", "30day": "30d", "30days": "30d",
        "90": "90d", "90day": "90d", "90days": "90d",
        "365": "1y", "year": "1y", "1year": "1y",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in {*_RANGE_DAYS, "custom"} else "3d"


def _parse_date(value: str):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _range_bounds() -> tuple[str, datetime, datetime, str]:
    mode = _range_key()
    today = datetime.now(_TZ).date()
    if mode == "custom":
        start_date = _parse_date(request.args.get("fbm_from"))
        end_date = _parse_date(request.args.get("fbm_to"))
        if start_date is None or end_date is None or start_date > end_date:
            mode = "3d"
        else:
            start_local = datetime(start_date.year, start_date.month, start_date.day, tzinfo=_TZ)
            end_local = datetime(end_date.year, end_date.month, end_date.day, tzinfo=_TZ) + timedelta(days=1)
            start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
            return mode, start_utc, end_utc, f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"

    days = _RANGE_DAYS.get(mode, 3)
    start_date = today - timedelta(days=days - 1)
    start_local = datetime(start_date.year, start_date.month, start_date.day, tzinfo=_TZ)
    end_local = datetime(today.year, today.month, today.day, tzinfo=_TZ) + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    label = {"3d": "Last 3 days", "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days", "1y": "Last year"}.get(mode, "Last 3 days")
    return mode, start_utc, end_utc, label


def _workflow_tab() -> str:
    value = str(request.args.get("fbm_tab") or "").strip().lower()
    return value if value in _WORKFLOW_TABS else ""


def _status_reason(status: str) -> str | None:
    value = str(status or "").strip().lower()
    if any(term in value for term in _REPLACEMENT_TERMS):
        return "replacements"
    if any(term in value for term in _REFUND_TERMS):
        return "refunds"
    return None


def _sds_committed(shipment) -> bool:
    if shipment is None or str(getattr(shipment, "provider", "") or "").strip().lower() != "sds":
        return False
    purchase_status = str(getattr(shipment, "purchase_status", "") or "").strip().lower()
    return bool(
        getattr(shipment, "label_purchased_at", None)
        or getattr(shipment, "carrier_accepted_at", None)
        or getattr(shipment, "first_movement_at", None)
        or getattr(shipment, "delivered_at", None)
        or getattr(shipment, "tracking_number", None)
        or purchase_status in {"confirmed", "purchased", "committed"}
    )


def _canonical_order_rank(row: MarketplaceOrder) -> tuple[int, ...]:
    status = str(getattr(row, "status", "") or "").strip().lower()
    issue_or_cancel = bool(_status_reason(status) or status in _CANCELLED_STATUSES or status.startswith("cancel"))
    dispatch_truth = bool(any(term in status for term in _DISPATCHED_STATUS_TERMS) or getattr(row, "tracking_number", None) or getattr(row, "shipped_at", None))
    processed_truth = bool(getattr(row, "processed_at", None) or status == "processed")
    return (1 if issue_or_cancel else 0, 1 if dispatch_truth else 0, 1 if processed_truth else 0, int(getattr(row, "id", 0) or 0))


def _canonical_order_rows(rows: list[MarketplaceOrder]) -> list[MarketplaceOrder]:
    selected: dict[tuple[int, str], MarketplaceOrder] = {}
    for row in rows:
        if row.store_id is None or not row.marketplace_order_id:
            continue
        key = (int(row.store_id), str(row.marketplace_order_id))
        current = selected.get(key)
        if current is None or _canonical_order_rank(row) > _canonical_order_rank(current):
            selected[key] = row
    return sorted(selected.values(), key=lambda row: int(row.id or 0), reverse=True)


def workflow_queue_for(row: MarketplaceOrder, shipment=None) -> str:
    """Canonical FBM lifecycle classifier shared by server and browser presentation."""
    from services import governed_fbm_dispatch_queue_alignment as dispatch
    return dispatch._aligned_workflow_queue_for(row, shipment)


def _row_matches_term(row: MarketplaceOrder, term: str) -> bool:
    if not term:
        return True
    needle = term.casefold()
    store = getattr(row, "store", None)
    warehouse = getattr(row, "warehouse_stock", None)
    values = (getattr(row, "marketplace_order_id", None), getattr(row, "marketplace_order_item_id", None), getattr(row, "sku", None), getattr(row, "tracking_number", None), getattr(row, "carrier", None), getattr(row, "status", None), getattr(store, "name", None) if store else None, getattr(store, "platform", None) if store else None, getattr(warehouse, "product_name", None) if warehouse else None)
    return any(needle in str(value or "").casefold() for value in values)


def _prime_shipment_relationships(shipments) -> None:
    by_id = {int(shipment.id): shipment for shipment in shipments if shipment is not None and getattr(shipment, "id", None) is not None}
    shipment_ids = sorted(by_id)
    if not shipment_ids:
        return
    reviews = db.session.query(FBMShipmentMappingReview).filter(FBMShipmentMappingReview.shipment_id.in_(shipment_ids)).all()
    review_by_shipment = {int(review.shipment_id): review for review in reviews}
    provider_cases = db.session.query(FBMProviderCase).filter(FBMProviderCase.shipment_id.in_(shipment_ids)).order_by(FBMProviderCase.id.asc()).all()
    cases_by_shipment: dict[int, list[FBMProviderCase]] = {}
    for case in provider_cases:
        cases_by_shipment.setdefault(int(case.shipment_id), []).append(case)
    for shipment_id, shipment in by_id.items():
        set_committed_value(shipment, "mapping_review", review_by_shipment.get(shipment_id))
        set_committed_value(shipment, "provider_cases", cases_by_shipment.get(shipment_id, []))


def _session_snapshot_rows() -> tuple[list[MarketplaceOrder], bool]:
    cached = getattr(g, "_bt38_fbm_session_rows", None)
    if cached is not None:
        return list(cached), bool(getattr(g, "_bt38_fbm_session_truncated", False))
    from services import governed_fbm_page_alignment as page_alignment
    _, start_at, end_at, _ = _range_bounds()
    eligible = (func.upper(func.coalesce(MarketplaceOrder.fulfillment_type, "")).notin_(("FBA", "AFN", "MCF")), ~func.lower(func.coalesce(MarketplaceOrder.status, "")).like("mcf_%"))
    requested = _page_size()
    broad_lookup = bool(_search_term() or _workflow_tab())
    candidate_limit = _RANGE_ROW_CAP + 1 if broad_lookup else min(_RANGE_ROW_CAP + 1, (requested * _RANGE_CANDIDATE_MULTIPLIER) + 1)
    candidates = (db.session.query(MarketplaceOrder).filter(*eligible).filter(MarketplaceOrder.store_id.isnot(None), MarketplaceOrder.marketplace_order_id.isnot(None)).filter(MarketplaceOrder.created_at >= start_at, MarketplaceOrder.created_at < end_at).options(joinedload(MarketplaceOrder.store), joinedload(MarketplaceOrder.warehouse_stock)).order_by(MarketplaceOrder.id.desc()).limit(candidate_limit).all())
    candidate_truncated = len(candidates) >= candidate_limit
    canonical = _canonical_order_rows(candidates)
    profiles = page_alignment._profile_map([row for row in canonical if _platform(row).strip().lower() == "amazon"])
    rows: list[MarketplaceOrder] = []
    for row in canonical:
        key = (int(row.store_id), str(row.marketplace_order_id))
        profile = profiles.get(key) if _platform(row).strip().lower() == "amazon" else None
        if page_alignment._workspace_fbm_eligible(row, profile):
            rows.append(row)
    g._bt38_fbm_session_rows = rows
    g._bt38_fbm_session_truncated = candidate_truncated
    return list(rows), candidate_truncated


def _persisted_workflow_snapshot() -> dict:
    cached = getattr(g, "_bt38_fbm_workflow_snapshot", None)
    if cached is not None:
        return cached
    from services import governed_fbm_page_alignment as page_alignment
    rows, truncated = _session_snapshot_rows()
    shipments = page_alignment._shipment_map(rows)
    grouped = {name: [] for name in _WORKFLOW_TABS}
    for row in rows:
        shipment = shipments.get((int(row.store_id), str(row.marketplace_order_id)))
        queue = workflow_queue_for(row, shipment)
        if queue in grouped:
            grouped[queue].append(row)
    snapshot = {"rows": grouped, "counts": {name: len(grouped[name]) for name in _WORKFLOW_TABS}, "truncated": truncated}
    g._bt38_fbm_workflow_snapshot = snapshot
    return snapshot


def workflow_counts() -> dict[str, int]:
    return dict(_persisted_workflow_snapshot()["counts"])


def _workflow_rows(limit: int):
    tab = _workflow_tab()
    if not tab:
        return None
    snapshot = _persisted_workflow_snapshot()
    rows = list(snapshot["rows"].get(tab) or [])
    return rows[:limit], len(rows) > limit or bool(snapshot["truncated"])


def _search_rows(limit: int):
    term = _search_term()
    if not term:
        return None
    rows, truncated = _session_snapshot_rows()
    matched = [row for row in rows if _row_matches_term(row, term)]
    return matched[:limit], len(matched) > limit or truncated


def _query_args_without(*names: str) -> dict[str, str]:
    omitted = set(names)
    allowed = ("fbm_range", "fbm_from", "fbm_to", "limit", "platform", "status", "fbm_tab", "search")
    return {name: str(request.args.get(name) or "").strip() for name in allowed if name not in omitted and str(request.args.get(name) or "").strip()}


def install_governed_fbm_global_search_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_global_search_alignment_installed", False):
        return
    from services import governed_fbm_page_alignment as page_alignment
    original_profile_map = page_alignment._profile_map
    original_shipment_map = page_alignment._shipment_map

    def request_cached_profile_map(rows):
        cache = getattr(g, "_bt38_fbm_profile_cache", None)
        if cache is None:
            cache = {}
            g._bt38_fbm_profile_cache = cache
        missing = [row for row in rows if row.store_id is not None and row.marketplace_order_id and (int(row.store_id), str(row.marketplace_order_id)) not in cache]
        if missing:
            cache.update(original_profile_map(missing))
        return {(int(row.store_id), str(row.marketplace_order_id)): cache.get((int(row.store_id), str(row.marketplace_order_id))) for row in rows if row.store_id is not None and row.marketplace_order_id and cache.get((int(row.store_id), str(row.marketplace_order_id))) is not None}

    def request_cached_shipment_map(rows):
        cache = getattr(g, "_bt38_fbm_shipment_cache", None)
        loaded = getattr(g, "_bt38_fbm_shipment_keys_loaded", None)
        if cache is None:
            cache = {}
            g._bt38_fbm_shipment_cache = cache
        if loaded is None:
            loaded = set()
            g._bt38_fbm_shipment_keys_loaded = loaded
        keys = {(int(row.store_id), str(row.marketplace_order_id)) for row in rows if row.store_id is not None and row.marketplace_order_id}
        missing_keys = keys - loaded
        if missing_keys:
            missing_rows = [row for row in rows if row.store_id is not None and row.marketplace_order_id and (int(row.store_id), str(row.marketplace_order_id)) in missing_keys]
            fresh = original_shipment_map(missing_rows)
            _prime_shipment_relationships(fresh.values())
            cache.update(fresh)
            loaded.update(missing_keys)
        return {key: cache.get(key) for key in keys if cache.get(key) is not None}

    def requested_limit():
        return _page_size()

    def session_rows(limit: int):
        rows, truncated = _session_snapshot_rows()
        search_result = _search_rows(limit)
        if search_result is not None:
            return search_result
        workflow_result = _workflow_rows(limit)
        if workflow_result is not None:
            return workflow_result
        return rows[:limit], bool(truncated or len(rows) > limit)

    def selected_health_period():
        return _range_bounds()

    def no_legacy_period_controls(_health):
        return ""

    def no_server_expand(html: str, *, visible_limit: int, has_more: bool) -> str:
        return html

    page_alignment._requested_limit = requested_limit
    page_alignment._profile_map = request_cached_profile_map
    page_alignment._shipment_map = request_cached_shipment_map
    page_alignment._health_period = selected_health_period
    page_alignment._period_controls = no_legacy_period_controls
    page_alignment._expand_control = no_server_expand

    app._bt38_fbm_global_search_alignment_installed = True
    app.logger.info("BT38 FBM history controls aligned: native GET 3/7/30/90/1y/custom range, exact 15/30/50/100 page size, request-cached persisted reads, no marketplace/provider reads")
