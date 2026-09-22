from pathlib import Path


def test_ship_by_deadline_uses_existing_exact_due_event_runtime():
    profile = Path(
        "services/governed_amazon_fbm_profile_event_alignment.py"
    ).read_text(encoding="utf-8")
    runtime = Path("services/governed_runtime_engine.py").read_text(
        encoding="utf-8"
    )

    assert 'source="amazon_fbm_ship_by_deadline"' in profile
    assert '"event_type": "amazon_fbm_ship_by_deadline"' in profile
    assert '"verify_after": ship_by_at' in profile
    assert "notify_governed_runtime_work(" in profile

    assert 'event_type == "amazon_fbm_ship_by_deadline"' in runtime
    assert "_execute_amazon_fbm_ship_by_deadline_event(event)" in runtime
    assert "refresh_exact_amazon_order(row)" in runtime


def test_ship_by_deadline_remains_exact_record_only():
    profile = Path(
        "services/governed_amazon_fbm_profile_event_alignment.py"
    ).read_text(encoding="utf-8")
    runtime = Path("services/governed_runtime_engine.py").read_text(
        encoding="utf-8"
    )

    executor_start = runtime.index(
        "def _execute_amazon_fbm_ship_by_deadline_event"
    )
    executor_end = runtime.index(
        "def _execute_mcf_auto_release_event", executor_start
    )
    executor = runtime[executor_start:executor_end]

    assert ".filter_by(store_id=store_id, marketplace_order_id=order_id)" in executor
    assert "refresh_exact_amazon_order(row)" in executor
    assert "get_orders" not in executor
    assert "run_governed_marketplace_import_refresh" not in executor
    assert "threading.Timer" not in profile
    assert "threading.Thread" not in profile


def test_terminal_order_does_not_arm_or_read_back_again():
    profile = Path(
        "services/governed_amazon_fbm_profile_event_alignment.py"
    ).read_text(encoding="utf-8")
    runtime = Path("services/governed_runtime_engine.py").read_text(
        encoding="utf-8"
    )

    assert '"cancelled", "canceled", "shipped", "dispatched", "delivered"' in profile
    assert '"cancelled", "canceled", "shipped", "dispatched", "delivered"' in runtime
    assert '"reason": "deadline_already_satisfied"' in runtime
