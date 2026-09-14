"""BT38 retired sync-path boundary proof.

The old marketplace execution surfaces remain inert compatibility shells.
Current runtime authority is the governed SystemConfig + Store fuse box; this
suite must not require the retired global force-closed runtime architecture.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_not_contains(path: str, forbidden: list[str]):
    source = read(path)
    present = [marker for marker in forbidden if marker in source]
    assert not present, f"{path} still contains forbidden old-sync markers: {present}"


def test_worker_and_scheduler_startup_are_disabled():
    source = read("sync_dispatcher.py")
    for marker in ["WORKERS_DISABLED", "start_dispatcher() blocked", "start_order_import_scheduler() blocked"]:
        assert marker in source
    for marker in ["threading.Thread", "while self.running", "_dispatcher_loop", "_process_store_queue", "_execute_job", "OrderImportScheduler", "SyncDispatcher"]:
        assert marker not in source


def test_queue_manager_cannot_create_or_process_jobs():
    source = read("queue_manager.py")
    assert "QUEUE_MANAGER_DISABLED = True" in source
    assert "OLD_SYNC_DISABLED = True" in source
    assert "MARKETPLACE_EXECUTION_DISABLED = True" in source
    assert "GOVERNED_PATH_REQUIRED = True" in source
    assert "queue_job_created" in source
    for marker in ["SyncJob(", "db.session.add(job)", "status='pending'", "status = 'running'", "status = 'completed'", "retry_count"]:
        assert marker not in source


def test_marketplace_services_have_no_live_api_markers():
    assert_not_contains("amazon_service.py", ["from sp_api", "sp_api.api", "Feeds(", "Inventories(", "ListingsItems(", "requests.get", "requests.post", "create_feed", "submit_feed"])
    assert_not_contains("ebay_service.py", ["requests.get", "requests.post", "api.ebay.com", "sandbox.ebay.com", "ReviseInventoryStatus", "GetItem", "GetMyeBay", "Trading API"])


def test_old_orchestration_services_are_disabled():
    required_pairs = {
        "sync_service.py": ["SYNC_SERVICE_DISABLED", "LEGACY_SYNC_ORCHESTRATION_DISABLED"],
        "smart_push_service.py": ["SMART_PUSH_DISABLED", "LEGACY_PUSH_ORCHESTRATION_DISABLED"],
        "auto_push_service.py": ["AUTO_PUSH_SERVICE_DISABLED", "LEGACY_AUTO_PUSH_DISABLED"],
        "warehouse_push_coordinator.py": ["WAREHOUSE_PUSH_COORDINATOR_DISABLED", "LEGACY_WAREHOUSE_PUSH_DISABLED"],
        "marketplace_order_processor.py": ["MARKETPLACE_ORDER_PROCESSOR_DISABLED", "LEGACY_ORDER_IMPORT_DISABLED"],
    }
    for path, markers in required_pairs.items():
        source = read(path)
        for marker in markers:
            assert marker in source, f"{path} missing disabled marker {marker}"


def test_runtime_gate_delegates_to_current_fuse_box_authority():
    source = read("services/runtime_gate.py")
    assert "from services.runtime_action_guard import is_runtime_action_allowed" in source
    assert "is_runtime_action_allowed(" in source
    assert '"source": "runtime_gate"' in source
    assert "RUNTIME_GATE_FORCE_CLOSED" not in source


def test_routes_do_not_expose_old_execution_or_mutation_paths():
    source = read("routes.py")
    forbidden_active_route_patterns = [
        "@bp.get(\"/api/diagnostics/ebay/health\")", "@bp.get(\"/api/diagnostics/ebay/policies\")",
        "@bp.get(\"/api/diagnostics/ebay/raw-import\")", "@bp.post(\"/api/admin/fix-sandbox-flag\")",
        "@bp.post(\"/api/admin/ebay/normalize-itemids\")", "@bp.route('/ebay-setup'", "@bp.route('/test-ebay-connection'",
    ]
    for marker in forbidden_active_route_patterns:
        assert marker not in source, f"Route still active and must be retired or blocked: {marker}"
    forbidden_execution_calls = [
        "enqueue_sync_job(", "smart_push_service.push_specific_sku", "sync_inventory_to_amazon", "sync_inventory_to_ebay",
        "import_inventory_from_ebay", "import_inventory_from_amazon", "authenticate_store(store)", "resolve_item_id_by_sku",
        "get_seller_profiles", "get_ebay_official_time",
    ]
    for marker in forbidden_execution_calls:
        assert marker not in source, f"routes.py still contains old execution call: {marker}"


def test_app_level_debug_and_startup_paths_are_not_active():
    source = read("app.py")
    for marker in ["@app.route(\"/debug/fba-local\")", "@app.route(\"/debug/fba-local-direct\")", "@app.route(\"/debug/fba-open\")"]:
        assert marker not in source, f"Debug route still active and must be removed/retired: {marker}"
    for marker in ["Sync dispatcher started", "Order import scheduler started", "dispatcher is the single execution path"]:
        assert marker not in source, f"Misleading startup claim remains: {marker}"


def assert_disabled_result(result):
    assert isinstance(result, dict)
    assert result["success"] is False
    assert result["execution_blocked"] is True
    assert result["old_sync_disabled"] is True
    assert result["marketplace_execution_disabled"] is True
    assert result["governed_path_required"] is True


def test_worker_scheduler_and_queue_calls_return_disabled_contract():
    import queue_manager
    import sync_dispatcher

    assert sync_dispatcher.OLD_SYNC_DISABLED is True
    assert sync_dispatcher.MARKETPLACE_EXECUTION_DISABLED is True
    assert sync_dispatcher.GOVERNED_PATH_REQUIRED is True
    assert_disabled_result(sync_dispatcher.start_dispatcher())
    assert_disabled_result(sync_dispatcher.start_order_import_scheduler())
    assert_disabled_result(sync_dispatcher.get_dispatcher().start())

    queued = queue_manager.enqueue_sync_job(1, queue_manager.JOB_PUSH_ITEM, {"sku": "FBA-CG-UN-05"})
    assert queued["success"] is False
    assert queued["execution_blocked"] is True
    assert queued["execution_started"] is False
    assert queued["queue_job_created"] is False
    assert queued["governed"] is True


def test_marketplace_service_methods_return_disabled_before_external_calls():
    import amazon_service
    import auto_push_service
    import ebay_service
    import marketplace_order_processor
    import smart_push_service
    import warehouse_push_coordinator

    amazon = amazon_service.AmazonAPIService()
    ebay = ebay_service.eBayAPIService()
    assert_disabled_result(amazon.update_inventory("FBA-CG-UN-05", 1))
    assert_disabled_result(amazon.update_listing_quantity_patch(sku="FBA-KA-OL-100-ML", quantity=1))
    assert_disabled_result(ebay.revise_inventory("EB-OD-CR-100g-X3", 1))
    assert_disabled_result(ebay.revise_fixed_price_item("EB-OD-CR-100g-X3", 1))
    assert_disabled_result(auto_push_service.run_auto_push())
    assert_disabled_result(smart_push_service.push_sku("FBA-CG-UN-05"))
    assert_disabled_result(marketplace_order_processor.import_orders())
    assert_disabled_result(warehouse_push_coordinator.push_stock("FBA-CG-UN-05"))


def test_shutdown_contract_constants_present_on_retired_modules():
    modules = ["amazon_service", "auto_push_service", "ebay_service", "marketplace_order_processor", "queue_manager", "smart_push_service", "sync_dispatcher", "sync_service", "warehouse_push_coordinator"]
    for module_name in modules:
        module = __import__(module_name)
        assert module.OLD_SYNC_DISABLED is True, module_name
        assert module.MARKETPLACE_EXECUTION_DISABLED is True, module_name
        assert module.GOVERNED_PATH_REQUIRED is True, module_name


def test_secondary_marketplace_entrypoints_are_disabled():
    import amazon_auth
    import amazon_rest_api
    import fba_fbm_helpers

    assert amazon_auth.OLD_SYNC_DISABLED is True
    assert amazon_auth.should_skip_amazon_sync(object())[0] is True
    client = amazon_rest_api.AmazonRestAPIClient({}, "A1F83G8C2ARO7P")
    success, message = client.update_inventory_quantity("FBA-CG-UN-05", 1, "seller")
    assert success is False
    assert "Old marketplace" in message
    success, message, store = fba_fbm_helpers.get_amazon_client_for_store(1)
    assert success is False
    assert store is None
    assert "Old marketplace" in message


def test_startup_banners_do_not_advertise_retired_marketplace_execution():
    source = read("app.py")
    stale_startup_claims = [
        "Sync Job logging (FBA import, FBM push, eBay sync)", "API Error tracking (Amazon, eBay)",
        "AMAZON FBA/FBM UNIFIED ARCHITECTURE", "Push to Amazon via: smart_push_service / Listings API",
        "smart_push_service filters FBA at query time",
    ]
    for marker in stale_startup_claims:
        assert marker not in source, f"Startup banner still advertises retired marketplace execution: {marker}"

    runtime_gate = read("services/runtime_gate.py")
    assert "SystemConfig + Store settings via services.runtime_action_guard" in runtime_gate
    assert "RUNTIME_GATE_FORCE_CLOSED" not in runtime_gate
