"""Wire the existing FBM history controls directly to the governed page reader.

This is presentation/read alignment only. It adds no marketplace/provider read,
worker, poller, writer or inventory path. Explicit date/search/page-size requests
are allowed to read the selected persisted Neon history window.
"""
from __future__ import annotations

from flask import g

import services.governed_fbm_global_search_alignment as controls
import services.governed_fbm_page_alignment as page


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
            if row.store_id is not None
            and row.marketplace_order_id
            and (int(row.store_id), str(row.marketplace_order_id)) not in cache
        ]
        if missing:
            cache.update(_original_profile_map(missing))
        return {
            (int(row.store_id), str(row.marketplace_order_id)): cache.get(
                (int(row.store_id), str(row.marketplace_order_id))
            )
            for row in rows
            if row.store_id is not None
            and row.marketplace_order_id
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
            for row in rows
            if row.store_id is not None and row.marketplace_order_id
        }
        missing_keys = keys - loaded
        if missing_keys:
            missing_rows = [
                row for row in rows
                if row.store_id is not None
                and row.marketplace_order_id
                and (int(row.store_id), str(row.marketplace_order_id)) in missing_keys
            ]
            fresh = _original_shipment_map(missing_rows)
            controls._prime_shipment_relationships(fresh.values())
            cache.update(fresh)
            loaded.update(missing_keys)
        return {key: cache.get(key) for key in keys if cache.get(key) is not None}

    def _selected_rows(limit: int):
        rows, truncated = controls._session_snapshot_rows()
        search_result = controls._search_rows(limit)
        if search_result is not None:
            return search_result
        workflow_result = controls._workflow_rows(limit)
        if workflow_result is not None:
            return workflow_result
        return rows[:limit], bool(truncated or len(rows) > limit)

    def _selected_period_controls(_health):
        return controls._controls_html()

    page._requested_limit = controls._page_size
    page._profile_map = _cached_profile_map
    page._shipment_map = _cached_shipment_map
    page._latest_distinct_fbm_rows = _selected_rows
    page._health_period = controls._range_bounds
    page._period_controls = _selected_period_controls
    page._expand_control = lambda html, *, visible_limit, has_more: html
    page._bt38_history_controls_aligned = True
