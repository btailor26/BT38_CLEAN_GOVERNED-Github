from pathlib import Path


SOURCE = Path("services/governed_fbm_exact_record_session_alignment.py").read_text()


def test_exact_event_never_rebuilds_fbm_page_or_snapshot():
    assert "event.stopImmediatePropagation()" in SOURCE
    assert "applyActiveFiltersToExactRow(row)" in SOURCE
    assert "BT38FBMApplyCommittedSnapshot" not in SOURCE
    assert "location.reload" not in SOURCE
    assert "fetch(" not in SOURCE
    assert "setInterval" not in SOURCE
    assert "setTimeout" not in SOURCE
    assert "EventSource" not in SOURCE


def test_active_filters_are_reapplied_only_to_changed_row():
    assert "window.BT38.getPageSession('fbm',fallback)" in SOURCE
    assert "row.dataset.fbmHistoryMatch=historyMatch?'1':'0'" in SOURCE
    assert "String(row.dataset.fbmQueue||'')===active" in SOURCE
    assert "row.hidden=!matches" in SOURCE
    assert "rows.forEach" not in SOURCE


def test_exact_committed_projection_is_handed_to_existing_consumers():
    assert "bt38-fbm-committed-snapshot-applied" in SOURCE
    assert "projection:projected" in SOURCE
    assert "order_id:orderId" in SOURCE
