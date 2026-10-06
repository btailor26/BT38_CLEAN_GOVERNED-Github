from pathlib import Path


SOURCE = Path("services/fbm_packlink_event_processor.py").read_text()


def _tracking_update_branch() -> str:
    start = SOURCE.index('if event_name == "shipment.tracking.update":')
    end = SOURCE.index("\n    _apply_lifecycle_state", start)
    return SOURCE[start:end]


def test_tracking_webhook_hydrates_exact_packlink_history_once():
    branch = _tracking_update_branch()
    assert branch.count("adapter.get_tracking_status(reference=reference)") == 1
    assert "tracking_history=tracking_history" in branch
    assert "history=tracking_history" in branch


def test_tracking_webhook_remains_event_driven_not_payload_only():
    branch = _tracking_update_branch()
    assert '"event_driven_provider_read": True' in branch
    assert '"webhook_only": True' not in branch
    assert "callback_history = _callback_tracking_history(data)" not in branch
