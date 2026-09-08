from pathlib import Path


ROW_TRUTH = Path("static/js/fbm_row_truth_alignment.js").read_text(encoding="utf-8")
CLARITY = Path("services/governed_order_clarity_alignment.py").read_text(encoding="utf-8")


def test_row_truth_alignment_is_render_only_and_zero_network():
    assert "fbm_row_truth_alignment.js" in CLARITY
    assert "fetch(" not in ROW_TRUTH
    assert "XMLHttpRequest" not in ROW_TRUTH
    assert "setInterval" not in ROW_TRUTH
    assert "setTimeout" not in ROW_TRUTH
    assert "EventSource" not in ROW_TRUTH


def test_journey_colours_are_reset_before_persisted_lifecycle_is_applied():
    assert "setBadge(pickedUp, false)" in ROW_TRUTH
    assert "setBadge(inTransit, false)" in ROW_TRUTH
    assert "setBadge(delivered, false)" in ROW_TRUTH
    assert "pickupStates.has(status)" in ROW_TRUTH
    assert "movementStates.has(status)" in ROW_TRUTH
    assert "status === 'delivered'" in ROW_TRUTH


def test_dispatched_rows_do_not_show_pre_dispatch_route_choices():
    assert "dispatchedStates.has(status)" in ROW_TRUTH
    assert "cell.innerHTML = promise" in ROW_TRUTH
    assert "Recommended shipping" in ROW_TRUTH
    assert "Pending automatic selection" in ROW_TRUTH
    assert "Marketplace / Packlink / Manual" in ROW_TRUTH
