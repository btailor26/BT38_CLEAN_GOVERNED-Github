from datetime import datetime
from types import SimpleNamespace

import services.fbm_db_delivery_promise_alignment as delivery_alignment
import services.governed_order_clarity_alignment as presentation_alignment


def _shipment(delivered_at=None):
    return SimpleNamespace(delivered_at=delivered_at)


def _promise(latest_delivery_at=None):
    return {"latest_delivery_at": latest_delivery_at}


def test_delivery_timing_contract_marks_delivered_late_from_persisted_timestamps():
    result = delivery_alignment._delivery_performance(
        _shipment(datetime(2026, 9, 3, 12, 0)),
        _promise(datetime(2026, 9, 1, 23, 59)),
    )
    assert result == "late"


def test_delivery_timing_contract_marks_on_time_delivery_from_persisted_timestamps():
    result = delivery_alignment._delivery_performance(
        _shipment(datetime(2026, 9, 1, 18, 0)),
        _promise(datetime(2026, 9, 1, 23, 59)),
    )
    assert result == "on_time"


def test_delivery_timing_contract_does_not_infer_delivery_without_courier_timestamp():
    result = delivery_alignment._delivery_performance(
        _shipment(None),
        _promise(datetime(2026, 9, 1, 23, 59)),
    )
    assert result == ""


def test_delivery_timing_contract_reports_timing_unavailable_without_persisted_promise():
    result = delivery_alignment._delivery_performance(
        _shipment(datetime(2026, 9, 1, 18, 0)),
        _promise(None),
    )
    assert result == "timing_unavailable"


def test_delivery_timing_projection_is_injected_into_rendered_fbm_row():
    source = open(delivery_alignment.__file__, encoding="utf-8").read()
    presentation = open(presentation_alignment.__file__, encoding="utf-8").read()

    assert 'performance = _delivery_performance(shipment, promise)' in source
    assert 'item["delivery_performance"] = performance' in source
    assert '"delivery_performance": performance' in source
    assert 'g.fbm_delivery_truth_by_order_id = rendered_truth' in source

    assert 'def _inject_db_delivery_truth' in presentation
    assert 'getattr(g, "fbm_delivery_truth_by_order_id", {})' in presentation
    assert 'data-delivery-performance=' in presentation
    assert '_inject_db_delivery_truth(html)' in presentation


def test_delivery_timing_alignment_is_db_only_and_provider_neutral():
    source = open(delivery_alignment.__file__, encoding="utf-8").read()
    presentation = open(presentation_alignment.__file__, encoding="utf-8").read()

    assert "requests." not in source
    assert "httpx." not in source
    assert "marketplace API" not in source
    assert "carrier provider" in source
    assert "db.session.commit" not in source

    assert "requests." not in presentation
    assert "httpx." not in presentation
    assert "db.session.commit" not in presentation
