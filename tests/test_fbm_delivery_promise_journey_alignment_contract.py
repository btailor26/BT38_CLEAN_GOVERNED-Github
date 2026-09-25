from pathlib import Path


JOURNEY = Path("static/js/fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")


def test_shipment_journey_and_row_use_one_persisted_db_milestone_mapping():
    assert "function persistedMilestones(row)" in JOURNEY
    assert "row?.dataset?.carrierAcceptedAt" in JOURNEY
    assert "row?.dataset?.firstMovementAt" in JOURNEY
    assert "row?.dataset?.deliveredAt" in JOURNEY
    assert "trackingEvents(row)" in JOURNEY
    assert "const firstScan = scans[0] || null;" in JOURNEY
    assert "pickedUp: Boolean(row?.dataset?.carrierAcceptedAt || pickupEventAt)" in JOURNEY
    assert "/\\bin[ _-]?transit\\b/" in JOURNEY
    assert "/\\bdelivered\\b/" in JOURNEY
    assert "const milestones = persistedMilestones(row);" in JOURNEY
    assert "'picked up': milestones.pickedUp" in JOURNEY
    assert "'in transit': milestones.inTransit" in JOURNEY
    assert "'delivered': deliveryProven(row)" in JOURNEY
    assert "return Boolean(row?.dataset?.deliveredAt);" in JOURNEY
    assert "function matchingEventTime(row, patterns)" in JOURNEY
    assert "pickedUpAt: row?.dataset?.carrierAcceptedAt || pickupEventAt" in JOURNEY
    assert "inTransitAt: row?.dataset?.firstMovementAt || movementEventAt" in JOURNEY
    assert "deliveredAt: row?.dataset?.deliveredAt || ''" in JOURNEY
    assert "if (milestones.pickedUp && /pickup not confirmed/i.test(text)) note.remove()" in JOURNEY


def test_delivery_performance_remains_independent_persisted_db_truth():
    assert "row?.dataset?.deliveryPerformance" in JOURNEY
    assert "performance === 'late'" in JOURNEY
    assert "bg-danger text-white\">Late" in JOURNEY


def test_journey_alignment_remains_render_only_and_zero_polling():
    assert "fetch(" not in JOURNEY
    assert "XMLHttpRequest" not in JOURNEY
    assert "setInterval" not in JOURNEY
    assert "EventSource" not in JOURNEY
