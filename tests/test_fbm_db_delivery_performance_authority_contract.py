from datetime import datetime
from pathlib import Path

from services.fbm_db_delivery_promise_alignment import _delivery_performance, _shipping_source, _shipment_tracking_authority


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "js" / "fbm_delivery_promise_journey_alignment.js").read_text(encoding="utf-8")
CLARITY = (ROOT / "services" / "governed_order_clarity_alignment.py").read_text(encoding="utf-8")


class Shipment:
    def __init__(self, delivered_at=None, provider="", label_source=""):
        self.delivered_at = delivered_at
        self.provider = provider
        self.label_source = label_source


def test_real_yodel_example_is_late_from_persisted_db_timestamps():
    shipment = Shipment(datetime(2026, 9, 5, 23, 36, 26, 8000))
    promise = {"latest_delivery_at": datetime(2026, 9, 4, 22, 59, 59)}
    assert _delivery_performance(shipment, promise) == "late"


def test_delivered_before_persisted_promise_is_on_time():
    shipment = Shipment(datetime(2026, 9, 3, 10, 0, 0))
    promise = {"latest_delivery_at": datetime(2026, 9, 4, 22, 59, 59)}
    assert _delivery_performance(shipment, promise) == "on_time"


def test_delivered_without_persisted_promise_does_not_guess():
    assert _delivery_performance(Shipment(datetime(2026, 9, 3, 10, 0, 0)), {}) == "timing_unavailable"


def test_shipping_source_uses_only_persisted_label_purchase_evidence():
    assert _shipping_source(Shipment(provider="packlink", label_source="packlink")) == "Packlink"
    assert _shipping_source(Shipment(provider="ebay_shipping", label_source="ebay_finances_shipping_label")) == "eBay Shipping"
    assert _shipping_source(Shipment(provider="amazon_buy_shipping")) == "Amazon Buy Shipping"
    assert _shipping_source(Shipment(provider="marketplace")) == ""
    assert _shipping_source(None) == ""


def test_tracking_presentation_uses_server_db_result_and_never_calls_provider():
    assert "deliveryPerformance" in JS
    assert "shippingSource" in JS
    assert "dataset.carrier" in JS
    assert "Date.now()" not in JS
    assert "promiseDate" not in JS
    assert "persistedState" not in JS
    assert "fetch(" not in JS
    assert "/packlink/status" not in JS
    assert "/amazon/tracking" not in JS


def test_rendered_rows_receive_request_scoped_db_truth_without_provider_read():
    assert "fbm_delivery_truth_by_order_id" in CLARITY
    assert "data-delivery-performance" in CLARITY
    assert "data-delivery-promise-at" in CLARITY
    assert "data-delivered-at" in CLARITY
    assert "data-shipping-source" in CLARITY
    assert "data-carrier" in CLARITY
    assert "requests." not in CLARITY


class TrackingShipment(Shipment):
    def __init__(self, tracking_number="", carrier="", service="", provider="", label_source="", provider_shipment_id=""):
        super().__init__(provider=provider, label_source=label_source)
        self.tracking_number = tracking_number
        self.carrier = carrier
        self.service = service
        self.provider_shipment_id = provider_shipment_id


class TrackingOrder:
    def __init__(self, tracking_number="", carrier=""):
        self.tracking_number = tracking_number
        self.carrier = carrier


def test_draft_shipment_cannot_override_marketplace_tracking_identity():
    shipment = TrackingShipment(carrier="Royal Mail", service="Tracked 48 Small Parcel", provider="packlink")
    order = TrackingOrder(tracking_number="T00TNA6517868770", carrier="Hermes UK")
    truth = _shipment_tracking_authority(shipment, order)
    assert truth == {
        "carrier": "Hermes UK",
        "service": "",
        "tracking_number": "T00TNA6517868770",
        "authority": "marketplace_order",
    }
    assert _shipping_source(shipment) == ""


def test_verified_shipment_tracking_owns_its_carrier_and_service():
    shipment = TrackingShipment(
        tracking_number="H0067A0359326254",
        carrier="Evri",
        service="ParcelShop Parcel",
        provider="packlink",
    )
    order = TrackingOrder(tracking_number="OTHER", carrier="Other")
    truth = _shipment_tracking_authority(shipment, order)
    assert truth["carrier"] == "Evri"
    assert truth["service"] == "ParcelShop Parcel"
    assert truth["tracking_number"] == "H0067A0359326254"
    assert truth["authority"] == "shipment"
    assert _shipping_source(shipment) == "Packlink"
