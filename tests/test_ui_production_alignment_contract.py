from pathlib import Path


CONTROLLER = Path("static/js/bt38-page-controller.js")
PRODUCT_LINKING_SESSION = Path("static/js/product-linking-session.js")
PRODUCT_LINKING = Path("templates/product_linking.html")
WAREHOUSE = Path("templates/warehouse.html")
WAREHOUSE_ROUTE = Path("governed_routes.py")
WAREHOUSE_GOVERNED_JS = Path("static/js/warehouse-governed.js")
WAREHOUSE_RUNTIME_VISIBILITY = Path("governed_runtime_visibility_routes.py")
STORES = Path("templates/stores.html")
MAIN = Path("main.py")
FBM_TRACKING_JOURNEY = Path("static/js/fbm_tracking_journey.js")
FBM_PAGE_ALIGNMENT = Path("services/governed_fbm_page_alignment.py")
UI_EVENT_SIGNAL = Path("services/governed_ui_event_signal.py")


def _source(path):
    return path.read_text(encoding="utf-8")


def test_product_linking_has_one_authoritative_session_controller():
    shared = _source(CONTROLLER)
    session = _source(PRODUCT_LINKING_SESSION)

    assert 'owner: "product-linking-session.js"' in shared
    assert "installLocalProductLinkingSearch" not in shared
    assert "configureCompleteWorkingSets" not in shared
    assert "wireAsyncProductLinking" not in shared
    assert "window.searchWarehouseForLinking = function" in session
    assert "window.filterFlatListings = function" in session


def test_product_linking_session_persists_until_an_exact_change_then_paginates_locally():
    source = _source(PRODUCT_LINKING_SESSION)

    assert "FULL_DATASET_LIMIT = 5000" in source
    assert "CACHE_TTL_MS" not in source
    assert "fetchFullSnapshotOnceDaily" not in source
    assert "fetchInitialSnapshotOnce" in source
    assert "snapshotExists" in source
    assert "window.indexedDB.open" in source
    assert "state.filtered = state.products.filter" in source
    assert "state.filtered.slice(start, start + state.perPage)" in source
    assert "perPage: 15" in source


def test_product_linking_changes_merge_only_affected_server_state():
    source = _source(PRODUCT_LINKING_SESSION)

    assert "window.linkListingToWarehouse = async function" in source
    assert "window.unlinkListing = function" in source
    assert "async function confirmExplicitUnlink()" in source

    link_start = source.index("window.linkListingToWarehouse = async function")
    unlink_prepare_start = source.index("window.unlinkListing = function", link_start)
    unlink_confirm_start = source.index("async function confirmExplicitUnlink()", unlink_prepare_start)
    wire_start = source.index("function wire()", unlink_confirm_start)

    link_block = source[link_start:unlink_prepare_start]
    unlink_prepare_block = source[unlink_prepare_start:unlink_confirm_start]
    unlink_confirm_block = source[unlink_confirm_start:wire_start]

    assert "fetch(" not in unlink_prepare_block
    assert "pendingExplicitUnlink = {" in unlink_prepare_block

    assert "/unlink" in unlink_confirm_block
    assert "user_confirmed: true" in unlink_confirm_block

    assert "applyCommittedRelationshipLocally(" in link_block
    assert "applyCommittedRelationshipLocally(" in unlink_confirm_block
    assert "await applyMutationContract(relationshipEvent, {" not in link_block
    assert "await applyMutationContract(data, {" not in unlink_confirm_block

    assert "await refreshAffectedRecord({" in link_block
    assert "Never retry the write automatically" in link_block

    assert "await clearSnapshot();" not in link_block
    assert "window.location.reload();" not in link_block
    assert "await clearSnapshot();" not in unlink_confirm_block
    assert "window.location.reload();" not in unlink_confirm_block

    assert "await hydrate(true)" not in source


def test_product_linking_has_no_timer_or_focus_refresh_path():
    source = _source(PRODUCT_LINKING_SESSION)
    boot = source[source.index("function boot()") :]

    assert "setTimeout" not in source
    assert "setInterval" not in source
    assert "visibilitychange" not in boot
    assert 'addEventListener("focus"' not in boot
    assert "refreshVisibleProductLinkingOnce" not in source


def test_shared_page_controller_searches_cached_rows_then_paginates_locally():
    source = _source(CONTROLLER)

    assert "page.filteredRows = page.rows.filter" in source
    assert "page.filteredRows.slice(start, end)" in source
    assert "page.currentPage = 1" in source
    assert "event.preventDefault()" in source


def test_default_page_size_is_15_and_can_expand_without_server_request():
    source = _source(CONTROLLER)

    assert "const allowedPageSizes = [15, 25, 30, 50, 100]" in source
    assert "perPage: 15" in source
    assert "allowedPageSizes.includes(parsed) ? parsed : 15" in source
    assert 'select.addEventListener("change"' in source


def test_warehouse_route_loads_complete_relevant_listing_working_set_once():
    source = _source(WAREHOUSE_ROUTE)
    start = source.index("# Design B:")
    end = source.index("rows = []", start)
    block = source[start:end]

    assert "Load the complete relevant Warehouse dataset once" in block
    assert ".all()" in block
    assert ".limit(" not in block
    assert ".offset(" not in block


def test_warehouse_kpis_use_distinct_truth_sources():
    source = _source(CONTROLLER)

    assert "Active linked listings" in source
    assert "/governed/warehouse/economics-batch?stock_ids=" in source
    assert "stock × COGS" in source
    assert "missing COGS" in source
    assert "/governed/warehouse/runtime-state" not in source
    assert "bt38-warehouse-runtime-status" in source
    assert "Runtime verified" in source
    assert "Loaded stock × price" not in source
    assert "Loaded marketplace listings" not in source


def test_warehouse_navigation_is_wired_to_existing_pages():
    source = _source(CONTROLLER)

    assert '"master stock": "/warehouse"' in source
    assert '"fba read only": "/fba-inventory"' in source
    assert '"group view": "/product-linking"' in source
    assert '"orders": "/orders"' in source


def test_templates_keep_required_controller_scripts():
    product_linking = _source(PRODUCT_LINKING)
    warehouse = _source(WAREHOUSE)

    assert "bt38-global-state.js" in product_linking
    assert "bt38-page-controller.js" in product_linking
    assert "bt38-page-controller.js" in warehouse


def test_warehouse_critical_paint_rules_precede_first_warehouse_markup():
    warehouse = _source(WAREHOUSE)
    critical = warehouse.index('id="bt38WarehouseCriticalPaint"')
    root = warehouse.index('<div class="bt38-enterprise-stock"')

    assert critical < root
    assert 'loading="lazy" decoding="async"' in warehouse


def test_warehouse_profit_replaces_duplicate_row_action_and_keeps_compact_selection_bar():
    warehouse = _source(WAREHOUSE)

    assert "<th>Profit</th>" in warehouse
    assert 'class="bt38-profit-action"' in warehouse
    assert '>Action<' not in warehouse
    assert '<span id="bt38SelectedCount">0</span> selected' in warehouse
    assert '<option value="">Action…</option>' in warehouse
    assert 'aria-label="Clear selection"' in warehouse


def test_warehouse_profitability_has_separate_auto_and_what_if_sections():
    warehouse = _source(WAREHOUSE)
    controller = _source(WAREHOUSE_GOVERNED_JS)

    assert "AUTO · MARKETPLACE" in warehouse
    assert "CALCULATOR · WHAT IF?" in warehouse
    assert "Calculator only. It does not save or update a marketplace listing." in warehouse
    assert "bt38AutoDefaultsSave" in controller
    assert "Save warehouse defaults" in controller
    assert "recalcWhatIf" in controller
    assert "warehouse-economics" in controller


def test_warehouse_profit_cells_batch_hydrate_from_local_economics_only():
    controller = _source(WAREHOUSE_GOVERNED_JS)
    runtime = _source(WAREHOUSE_RUNTIME_VISIBILITY)

    assert "loadVisibleProfitability" in controller
    assert "/governed/warehouse/economics-batch?stock_ids=" in controller
    assert "renderRowProfit" in controller
    assert "loadVisibleProfitability();" in controller
    assert ".filter(row => !row.hidden)" in controller
    assert "scheduleVisibleProfitabilityRefresh" in controller
    assert "e.stopImmediatePropagation();" in controller
    assert '"marketplace_calls": False' in runtime


def test_warehouse_economics_save_refreshes_only_the_saved_row():
    controller = _source(WAREHOUSE_GOVERNED_JS)
    start = controller.index("const save = e.target")
    end = controller.index("document.addEventListener('input'", start)
    block = controller[start:end]

    assert "if (row) await loadEconomics(row);" in block
    assert "await loadVisibleProfitability();" not in block


def test_warehouse_runtime_heartbeat_reads_fuse_config_in_one_query():
    runtime = _source(WAREHOUSE_RUNTIME_VISIBILITY)
    start = runtime.index("def governed_warehouse_runtime_state")
    end = runtime.index("def governed_warehouse_economics_batch", start)
    block = runtime[start:end]

    assert "SystemConfig.key.in_(fuse_keys)" in block
    assert ".all()" in block
    assert "filter_by(key=key).first()" not in block


def test_warehouse_profit_batch_never_becomes_a_marketplace_write_path():
    controller = _source(WAREHOUSE_GOVERNED_JS)
    runtime = _source(WAREHOUSE_RUNTIME_VISIBILITY)

    batch_start = runtime.index('def governed_warehouse_economics_batch')
    single_start = runtime.index('def governed_warehouse_economics(stock_id', batch_start)
    batch_block = runtime[batch_start:single_start]

    assert "MarketplaceListing" not in batch_block
    assert "push_marketplace_listing" not in batch_block
    assert "amazon" not in batch_block.lower()
    assert "ebay" not in batch_block.lower()
    assert "postJson(`/governed/warehouse/economics-batch" not in controller


def test_warehouse_economics_save_is_local_only_and_reuses_existing_cost_fields():
    source = _source(WAREHOUSE_RUNTIME_VISIBILITY)

    assert '/governed/warehouse/<int:stock_id>/economics' in source
    assert '/governed/warehouse/economics-batch' in source
    assert '"unit_cost": "unit_cost"' in source
    assert '"product_weight_kg": "product_weight_kg"' in source
    assert '"shipping_cost_per_kg": "shipping_cost_per_kg"' in source
    assert '"commission_rate": "commission_rate"' in source
    assert '"marketplace_write": False' in source
    assert '"marketplace_calls": False' in source
    assert "push_marketplace_listing" not in source


def test_ebay_commercial_oauth_uses_one_store_aware_authorization_code_flow():
    routes = _source(WAREHOUSE_ROUTE)
    authorize = routes.split("def governed_ebay_oauth_authorize():", 1)[1]
    authorize = authorize.split("def governed_ebay_oauth_callback():", 1)[0]
    callback = routes.split("def governed_ebay_oauth_callback():", 1)[1]
    callback = callback.split("def governed_ebay_oauth_refresh_token():", 1)[0]

    assert "governed_ebay_oauth_scopes()" in authorize
    assert '"response_type": "code"' in authorize
    assert '"redirect_uri": runame' in authorize
    assert 'session["governed_ebay_oauth_store_id"] = store.id' in authorize
    assert "auth.ebay.com/oauth2/authorize" in authorize
    assert "signin.ebay.com/ws/eBayISAPI.dll" not in authorize

    assert '"grant_type": "authorization_code"' in callback
    assert 'state_store_id = state_payload.get("store_id")' in callback
    assert 'state_intent == "connect_ebay_store"' in callback
    assert 'selected_store_id = state_store_id' in callback
    assert "_resolve_governed_ebay_oauth_store(selected_store_id)" in callback
    assert 'session.get("governed_ebay_oauth_store_id")' not in callback
    assert '"refresh_token": token.get("refresh_token") or existing.get("refresh_token")' in callback
    assert '"oauth_requested_scope": scopes' in callback
    assert "ensure_ebay_order_notification_registration(" in callback
    assert 'return redirect(f"/stores?ebay_oauth=success&store_id={store.id}")' in callback


def test_ebay_store_ui_never_uses_developer_portal_or_legacy_authnauth():
    stores = _source(STORES)

    assert "developer.ebay.com" not in stores
    assert "signin.ebay.com/ws/eBayISAPI.dll" not in stores
    assert "/ebay-oauth/connect" in stores
    assert "/ebay-oauth/authorize" not in stores
    assert "/ebay-oauth/authorize?store_id=" not in stores


def test_ebay_store_ui_keeps_oauth_first_connect_only():
    stores = _source(STORES)

    assert "'AUTHORIZATION_REQUIRED' in store.api_key" not in stores
    assert "'Insufficient permissions' in store.api_key" not in stores
    assert "Permission approval required" not in stores
    assert "Approve eBay" not in stores

    # Once an eBay Store exists, its card must not send the customer back
    # through seller consent. Stored refresh-token authority owns renewal.
    cards_guard = stores.index("{% if stores %}", stores.index("<div class=\"row\">"))
    card_start = stores.index("{% for store in stores %}", cards_guard)
    empty_state = stores.index("{% else %}", card_start)
    card_section = stores[card_start:empty_state]
    assert 'href="/ebay-oauth/authorize"' not in card_section


def test_web_entrypoint_does_not_run_ebay_recovery_during_import():
    main = _source(MAIN)

    assert "align_ebay_notifications_and_recover_missed_changes" not in main
    assert "governed_ebay_post_deploy_alignment" not in main
    assert "start_event_only_runtime" not in main


def test_fbm_committed_refresh_is_exact_row_and_event_driven():
    journey = _source(FBM_TRACKING_JOURNEY)
    exact = _source(Path("services/governed_fbm_exact_record_session_alignment.py"))
    page = _source(FBM_PAGE_ALIGNMENT)
    signal = _source(UI_EVENT_SIGNAL)

    # Tracking Journey is presentation-only; committed DB refresh has one owner.
    assert "X-BT38-UI-Refresh':'targeted'" not in journey
    assert "bt38-marketplace-event" not in journey
    assert "setInterval(" not in journey

    # The committed event changes the existing browser row and then triggers
    # the same session render used by History, Health and lifecycle counters.
    # A targeted server HTML fetch is legacy code, not a requirement.
    assert "bt38-marketplace-event" in exact
    assert "findRow(orderId)" in exact
    assert "row.dataset.fbmHistoryAt||row.dataset.fbmCreatedAt" in exact
    assert "BT38FBMApplyCommittedSnapshot" in exact
    assert "bt38-fbm-committed-snapshot-applied" in exact
    assert "stopImmediatePropagation" in exact
    assert "X-BT38-UI-Refresh" not in exact
    assert "fetch('/fbm" not in exact
    assert "setInterval(" not in exact

    # The old targeted route may remain for compatibility but is no longer
    # called by the browser's committed event flow.
    assert 'request.headers.get("X-BT38-UI-Refresh") == "targeted"' in page
    assert "MarketplaceOrder.marketplace_order_id == targeted_marketplace_order_id" in page
    assert 'return render_template("_fbm_history_rows.html", orders=orders)' in page

    assert '"marketplace_order_id": getattr(row, "marketplace_order_id", None)' not in signal
    assert 'scope["marketplace_order_id"] = getattr(row, "marketplace_order_id", None)' in signal
    assert 'source="committed_marketplace_state"' in signal


def test_fbm_committed_refresh_is_scoped_to_one_marketplace_order():
    """A committed FBM event must never request an unscoped full FBM snapshot."""
    source = _source(Path("static/js/bt38-live-page-refresh.js"))
    assert "refreshUrl.searchParams.set('bt38_marketplace_order_id', marketplaceOrderId)" in source
    assert "if (!marketplaceOrderId) return false" in source
    assert "refreshUrl.searchParams.set('bt38_store_id', storeId)" in source
    assert "if (!/^[1-9][0-9]*$/.test(storeId)) return false;" in source
    assert "fetch(refreshUrl.toString()" in source


def test_fbm_targeted_backend_requires_exact_marketplace_order_identity():
    source = _source(FBM_PAGE_ALIGNMENT)
    assert "if targeted_refresh and not targeted_marketplace_order_id:" in source
    assert "if targeted_refresh and targeted_marketplace_order_id:" in source
    assert "MarketplaceOrder.marketplace_order_id == targeted_marketplace_order_id" in source
    assert "MarketplaceOrder.store_id == targeted_store_id" in source
    assert "_bt38_customer_store_or_404(targeted_store_id)" in source
    assert "if targeted_store_id <= 0:" in source
    assert 'return render_template("_fbm_history_rows.html", orders=[]), 400' in source


def test_warehouse_exact_event_refresh_reindexes_local_session_rows():
    """A replaced Warehouse DOM row must not leave stale local filter data."""
    shared = _source(Path("static/js/bt38-live-page-refresh.js"))
    controller = _source(CONTROLLER)
    assert "currentRow.replaceWith(document.importNode(freshRow, true));" in shared
    assert "window.BT38.PageController.refreshTableCache('warehouse')" in shared
    assert "refreshTableCache(name) { const cached = cacheRows(name); if (cached) filter(name, true);" in controller


def test_warehouse_unlinked_stock_not_hidden_by_listing_page_size():
    """Unlinked master stock remains in the browser working set above 15 listings."""
    source = _source(Path("governed_routes.py"))
    warehouse = source.split("def governed_warehouse_page():", 1)[1].split(
        '@governed_bp.post("/governed/actions/sku/dry-run")', 1
    )[0]
    assert "if len(rows) < row_limit:" not in warehouse
    assert "unlinked_stock = (" in warehouse
    assert "if stock.id in linked_stock_ids:" in warehouse


def test_warehouse_bottom_pager_has_one_change_owner():
    """The local controller, not an inline handler, owns Warehouse page-size changes."""
    template = _source(Path("templates/warehouse.html"))
    controller = _source(Path("static/js/bt38-page-controller.js"))
    assert template.count('id="bt38ResultsPerPageSelect"') == 1
    assert '<select id="bt38ResultsPerPageSelect" name="per_page">' in template
    assert 'select.addEventListener("change", () => { page.currentPage = 1; render(page.name); })' in controller


def test_fba_stock_page_is_authenticated_and_scoped_to_customer_stores():
    source = _source(WAREHOUSE_ROUTE)
    fba = source.split("@governed_bp.route('/amazon-fba-stock')", 1)[1].split('@governed_bp.get("/governed/audit/runtime-understanding")', 1)[0]
    assert "@login_required" in fba.split("def amazon_fba_stock():", 1)[0]
    assert "account_id, store_ids, _, _ = _bt38_customer_scope()" in fba
    assert "if account_id is None:" in fba
    assert "Store.id.in_(store_ids)" in fba
    assert "AmazonFBAInventory.query.filter(AmazonFBAInventory.store_id.in_(store_ids))" in fba
    assert fba.count("AmazonFBAInventory.store_id.in_(store_ids)") >= 5


def test_listings_and_groups_use_one_bottom_local_pager():
    listings = _source(Path("templates/listings.html"))
    groups = _source(Path("templates/groups.html"))
    pager = _source(Path("static/js/bt38-listings-local-pager.js"))
    assert listings.count('id="bt38ListingsBottomPager"') == 1
    assert groups.count('id="bt38GroupsBottomPager"') == 1
    assert 'id="bt38ListingsPageSize"' in listings
    assert 'id="bt38GroupsPageSize"' in groups
    assert "fetch(" not in pager
    assert "window.filterGroups = function filterGroups()" in groups


def test_fbm_all_three_order_read_paths_are_customer_store_scoped():
    page = _source(Path("services/governed_fbm_page_alignment.py"))
    history = _source(Path("services/governed_fbm_global_search_alignment.py"))
    ordinary = page.split("def _latest_distinct_fbm_rows(", 1)[1].split("\ndef ", 1)[0]
    shipping = page.split("def bounded_shipping_options():", 1)[1]
    snapshot = history.split("def _session_snapshot_rows()", 1)[1].split("\ndef ", 1)[0]
    assert "MarketplaceOrder.store_id.in_(store_ids)" in ordinary
    assert "MarketplaceOrder.store_id.in_(store_ids)" in shipping
    assert "MarketplaceOrder.store_id.in_(store_ids)" in snapshot
    assert "_bt38_customer_scope()" in ordinary
    assert "_bt38_customer_scope()" in shipping
    assert "_bt38_customer_scope()" in snapshot


def test_listings_local_pager_targets_rendered_table_and_asset_version_is_optional():
    listings = _source(Path("templates/listings.html"))
    pager = _source(Path("static/js/bt38-listings-local-pager.js"))
    assert listings.count('id="bt38ListingsTable"') == 1
    assert "getElementById('bt38ListingsTable')" in pager
    assert "config.get('BT38_ASSET_VERSION'" in listings


def test_fbm_page_imports_flask_request_context_for_working_set_status():
    source = _source(FBM_PAGE_ALIGNMENT)
    assert "from flask import g, jsonify, request, render_template" in source
    assert "g._bt38_fbm_working_set_truncated = bool(has_more)" in source


def test_fbm_browser_session_health_override_accepts_page_rows():
    page = _source(FBM_PAGE_ALIGNMENT)
    authority = _source(Path("services/governed_fbm_browser_session_authority_alignment.py"))
    assert "health = _health_summary(rows)" in page
    assert "def _browser_session_health_shell(rows=None) -> dict:" in authority
    assert "page._health_summary = _browser_session_health_shell" in authority


def test_warehouse_shared_list_bar_does_not_install_server_navigation():
    source = _source(Path("static/js/bt38-live-page-refresh.js"))
    assert "if (cleanPath() === '/warehouse') return;" in source
    assert "Warehouse pagination is owned by bt38-page-controller.js" in source


def test_notification_bell_does_not_read_database_on_page_wake():
    source = _source(Path("templates/base.html"))
    bell = source.split('id="bt38NotificationPanelScript"', 1)[1].split("</script>", 1)[0]
    assert 'panel.addEventListener("show.bs.offcanvas"' in bell
    assert 'window.addEventListener(\n            "pageshow"' not in bell
    assert 'document.addEventListener(\n            "visibilitychange"' not in bell
    assert "hydrateBellAfterWake" not in bell


def test_notification_panel_reuses_session_snapshot_on_repeat_open():
    source = _source(Path("templates/base.html"))
    bell = source.split('id="bt38NotificationPanelScript"', 1)[1].split("</script>", 1)[0]
    handler = bell.split('panel.addEventListener("show.bs.offcanvas"', 1)[1].split('});', 1)[0]
    assert "await loadNotifications();" in handler
    assert "stale = true;" not in handler


def test_warehouse_kpi_fallbacks_never_show_fabricated_values():
    source = _source(WAREHOUSE)
    assert "<strong>1,156</strong>" not in source
    assert "<strong>£183k</strong>" not in source
    assert "stats.listing_count" in source
    assert "stats.inventory_value" in source
    assert 'else "0"' in source
    assert 'else "0.00"' in source
    route = _source(WAREHOUSE_ROUTE)
    assert 'html.replace("<strong>1,156</strong>"' not in route
    assert 'html.replace("<strong>£183k</strong>"' not in route


def test_warehouse_initial_inventory_value_uses_scoped_sellable_cogs():
    route = _source(WAREHOUSE_ROUTE)
    block = route.split("    listing_count = (", 1)[1].split("    stats = SimpleNamespace(", 1)[0]
    assert 'filter(MarketplaceListing.store_id.in_(store_ids))' in block
    assert 'filter(~MarketplaceListing.title.ilike("Amazon SKU%"))' in block
    assert "func.sum(sellable * func.coalesce(WarehouseStock.unit_cost, 0))" in block
    assert "filter(WarehouseStock.warehouse_id.in_(warehouse_ids))" in block
    assert 'getattr(row, "price"' not in block



def test_warehouse_status_does_not_query_neon_on_navigation():
    template = _source(WAREHOUSE)
    controller = _source(CONTROLLER)
    assert "<strong>Not checked</strong>" in template
    assert 'fetch("/governed/warehouse/runtime-state"' not in controller
    assert "updateWarehouseStatusKpi()" not in controller
    assert 'addEventListener("bt38-warehouse-runtime-status"' in controller
