from types import SimpleNamespace

from services import governed_fbm_fba_pending_status_alignment  # noqa: F401
from services import governed_fbm_fba_visibility_alignment as visibility


def row(*, fulfillment="FBA", status="processed", shipped_at=None, tracking=None, carrier=None):
    return SimpleNamespace(
        fulfillment_type=fulfillment,
        status=status,
        shipped_at=shipped_at,
        tracking_number=tracking,
        carrier=carrier,
    )


def test_internal_processed_without_shipment_remains_pending():
    assert visibility._queue_for(row()) == "pending"


def test_real_pending_remains_pending():
    assert visibility._queue_for(row(status="pending")) == "pending"


def test_shipped_fba_moves_to_fba_section():
    assert visibility._queue_for(row(status="shipped")) == "fba"


def test_delivered_fba_remains_in_fba_section():
    assert visibility._queue_for(row(status="delivered")) == "fba"


def test_processed_with_shipment_evidence_is_not_falsely_kept_pending():
    assert visibility._queue_for(row(shipped_at=object())) is None


def test_non_fba_processed_order_is_unchanged():
    assert visibility._queue_for(row(fulfillment="FBM")) is None
