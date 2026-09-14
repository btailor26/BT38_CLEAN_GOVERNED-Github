from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEALTH = (ROOT / "services" / "governed_fbm_all_orders_health_alignment.py").read_text(encoding="utf-8")
SEARCH = (ROOT / "services" / "governed_fbm_global_search_alignment.py").read_text(encoding="utf-8")
CLARITY = (ROOT / "services" / "governed_order_clarity_alignment.py").read_text(encoding="utf-8")
SESSION_JS = (ROOT / "static" / "js" / "fbm_event_session_refresh_alignment.js").read_text(encoding="utf-8")
PAGE_CONTROLLER = (ROOT / "static" / "js" / "bt38-page-controller.js").read_text(encoding="utf-8")


def test_fbm_history_defaults_to_seven_days_and_history_is_date_scoped():
    assert "install_governed_fbm_all_orders_health_alignment" in CLARITY
    assert 'request.args.get("fbm_range") or "7d"' in HEALTH
    assert '"7d": (7, "Last 7 days")' in HEALTH
    assert '"30d": (30, "Last 30 days")' in HEALTH
    assert '"90d": (90, "Last 90 days")' in HEALTH
    assert '"1y": (365, "Last 1 year")' in HEALTH
    assert 'mode == "custom"' in HEALTH
    assert 'MarketplaceOrder.created_at >= start_at' in HEALTH
    assert 'MarketplaceOrder.created_at < end_at' in HEALTH
    assert 'global_search._session_snapshot_rows = selected_range_snapshot_rows' in HEALTH


def test_normal_fbm_page_read_is_bounded_to_selected_presentation_size():
    assert '_PAGE_SIZES = (15, 30, 50, 100)' in HEALTH
    assert 'visible_limit = _persisted_page_size()' in HEALTH
    assert 'candidate_limit = min(401, (visible_limit * 4) + 1)' in HEALTH
    assert '.limit(candidate_limit)' in HEALTH
    assert 'if len(rows) >= visible_limit:' in HEALTH
    assert 'page_alignment._requested_limit = _persisted_page_size' in HEALTH


def test_fbm_health_uses_selected_date_window_without_loading_warehouse_payloads():
    assert 'def _health_rows()' in HEALTH
    assert '.options(joinedload(MarketplaceOrder.store))' in HEALTH
    assert 'joinedload(MarketplaceOrder.warehouse_stock)' in HEALTH
    assert 'total = len(order_rows)' in HEALTH
    assert 'global_search.workflow_queue_for(row, shipment)' in HEALTH
    assert 'queue == "ready_dispatch"' in HEALTH
    assert 'queue == "dispatched"' in HEALTH
    assert "awaiting_carrier_acceptance" in HEALTH
    assert "acceptance_overdue" in HEALTH


def test_fbm_page_size_is_15_30_50_100_and_server_wired():
    assert '<option value="15"' in HEALTH
    assert '<option value="30"' in HEALTH
    assert '<option value="50"' in HEALTH
    assert '<option value="100"' in HEALTH
    assert 'name="limit"' in HEALTH
    assert 'onchange="this.form.submit()"' in HEALTH
    assert 'session["bt38_fbm_page_size"] = value' in HEALTH
    assert 'session.get("bt38_fbm_page_size", 15)' in HEALTH
    assert 'const allowedPageSizes = [15, 30, 50, 100];' in SESSION_JS
    assert "getPageSession('fbm'" in SESSION_JS
    assert "setPageSession('fbm'" in SESSION_JS
    assert 'The server value is authoritative' in SESSION_JS
    assert 'const allowedPageSizes = [15, 25, 30, 50, 100];' in PAGE_CONTROLLER


def test_operational_health_remains_read_only_and_preserves_fbm_guards():
    assert "_workspace_fbm_eligible" in HEALTH
    assert '"FBA", "AFN", "MCF"' in HEALTH
    assert "requests." not in HEALTH
    assert "db.session.add" not in HEALTH
    assert "db.session.commit" not in HEALTH
    assert "get_or_refresh_amazon_profile" not in HEALTH


def test_ready_queue_alone_owns_shipping_action_headline():
    assert '"shipping_actions": dispatch_due,' in HEALTH
    assert '"shipping_actions": dispatch_due + overdue' not in HEALTH
    assert '"dispatched": dispatched' in HEALTH
    assert '"overdue": overdue' in HEALTH
    assert "Current Ready-to-dispatch orders drive this number" in HEALTH
    assert 'platform.casefold() == "amazon"' in HEALTH
    assert 'page_alignment._health_html = operational_health_html' in HEALTH
    assert 'html.replace(mapping_card, "")' in HEALTH
