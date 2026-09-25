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


def test_row_truth_does_not_compete_for_journey_colour_ownership():
    assert "function alignJourney(" not in ROW_TRUTH
    assert "setBadge(pickedUp" not in ROW_TRUTH
    assert "setBadge(inTransit" not in ROW_TRUTH
    assert "setBadge(delivered" not in ROW_TRUTH
    assert "Journey colour ownership lives only in fbm_delivery_promise_journey_alignment.js" in ROW_TRUTH


def test_dispatched_rows_do_not_show_pre_dispatch_route_choices():
    assert "dispatchedStates.has(status)" in ROW_TRUTH
    assert "cell.innerHTML = promise" in ROW_TRUTH
    assert "Recommended shipping" in ROW_TRUTH
    assert "Pending automatic selection" in ROW_TRUTH
    assert "Marketplace / Packlink / Manual" in ROW_TRUTH
