"""
Proof tests for BT38 worker shutdown phase.

These tests deliberately do not import app.py because app.py performs startup work.
They validate the sync_dispatcher module itself is a disabled compatibility shell.

The required result before adding any new execution route:
- no dispatcher loop implementation
- no store queue worker implementation
- no job execution implementation
- no order import scheduler implementation
- start_dispatcher() returns without starting anything
- start_order_import_scheduler() returns without starting anything
"""

import inspect
import sync_dispatcher


def test_sync_dispatcher_module_has_no_legacy_worker_classes():
    assert not hasattr(sync_dispatcher, "SyncDispatcher")
    assert not hasattr(sync_dispatcher, "OrderImportScheduler")


def test_sync_dispatcher_module_has_no_worker_loop_methods():
    forbidden_names = {
        "_dispatcher_loop",
        "_process_store_queue",
        "_execute_job",
        "_execute_full_sync",
        "_execute_push_item",
        "_execute_push_warehouse_item",
        "_execute_import_listings",
        "_execute_order_import",
        "_execute_auto_push_dry_run",
        "_scheduler_loop",
        "_run_scheduled_import",
    }

    module_names = set(dir(sync_dispatcher))
    assert forbidden_names.isdisjoint(module_names)

    for _, obj in inspect.getmembers(sync_dispatcher):
        if inspect.isclass(obj):
            class_names = set(dir(obj))
            assert forbidden_names.isdisjoint(class_names)


def test_start_dispatcher_is_disabled_noop(monkeypatch):
    def forbidden_thread(*args, **kwargs):
        raise AssertionError("threading.Thread must not be called by start_dispatcher")

    # If someone reintroduces threading into the module, this catches it.
    if hasattr(sync_dispatcher, "threading"):
        monkeypatch.setattr(sync_dispatcher.threading, "Thread", forbidden_thread)

    result = sync_dispatcher.start_dispatcher()
    assert result is None

    dispatcher = sync_dispatcher.get_dispatcher()
    assert getattr(dispatcher, "running", None) is False


def test_start_order_import_scheduler_is_disabled_noop(monkeypatch):
    def forbidden_thread(*args, **kwargs):
        raise AssertionError("threading.Thread must not be called by start_order_import_scheduler")

    # If someone reintroduces threading into the module, this catches it.
    if hasattr(sync_dispatcher, "threading"):
        monkeypatch.setattr(sync_dispatcher.threading, "Thread", forbidden_thread)

    result = sync_dispatcher.start_order_import_scheduler()
    assert result is None

    scheduler = sync_dispatcher.get_order_import_scheduler()
    assert getattr(scheduler, "running", None) is False


def test_worker_module_source_contains_disabled_marker_only():
    source = inspect.getsource(sync_dispatcher)

    required_markers = [
        "WORKERS_DISABLED",
        "start_dispatcher() blocked",
        "start_order_import_scheduler() blocked",
        "No dispatcher loop, store queue worker, import, sync, or push worker was started",
        "No scheduled order import loop was started",
    ]
    for marker in required_markers:
        assert marker in source

    forbidden_markers = [
        "threading.Thread",
        "while self.running",
        "get_next_pending_job",
        "mark_job_running",
        "sync_store(",
        "sync_item_to_store(",
        "sync_warehouse_stock_to_store(",
        "import_listings_from_store(",
        "OrderImportService.run_scheduled_import",
    ]
    for marker in forbidden_markers:
        assert marker not in source
