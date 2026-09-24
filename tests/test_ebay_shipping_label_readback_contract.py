"""Contract tests for governed eBay shipment Trading readback."""
from datetime import datetime
from unittest.mock import Mock

from services import governed_ebay_shipping_label_readback as readback


TRADING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<GetOrdersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <OrderArray>
    <Order>
      <OrderID>27-15097-79712</OrderID>
      <ShippingServiceSelected>
        <ShippingService>UK_RoyalMail48</ShippingService>
        <ShippingPackageInfo>
          <ActualDeliveryTime>2026-09-09T08:09:49.000Z</ActualDeliveryTime>
        </ShippingPackageInfo>
      </ShippingServiceSelected>
      <TransactionArray>
        <Transaction>
          <Item><ItemID>127951772415</ItemID></Item>
          <TransactionID>10087798582227</TransactionID>
          <OrderLineItemID>127951772415-10087798582227</OrderLineItemID>
          <ShippingDetails>
            <ShipmentTrackingDetails>
              <ShippingCarrierUsed>InPost Shops</ShippingCarrierUsed>
              <ShipmentTrackingNumber>87RKL8500193A024</ShipmentTrackingNumber>
            </ShipmentTrackingDetails>
          </ShippingDetails>
        </Transaction>
      </TransactionArray>
    </Order>
  </OrderArray>
</GetOrdersResponse>
"""


def _response(*, status_code=200, content=TRADING_XML):
    response = Mock()
    response.status_code = status_code
    response.content = content
    return response


def test_trading_shipment_truth_reads_carrier_tracking_and_delivery(monkeypatch):
    post = Mock(return_value=_response())
    monkeypatch.setattr(readback.requests, "post", post)

    truth = readback._trading_shipment_truth(
        access_token="test-token",
        order_id="27-15097-79712",
    )

    assert truth == {
        "tracking_rows": [
            {
                "tracking_number": "87RKL8500193A024",
                "carrier": "InPost Shops",
            }
        ],
        "delivered_at": datetime(2026, 9, 9, 8, 9, 49),
        "line_identities": [
            {
                "item_id": "127951772415",
                "transaction_id": "10087798582227",
                "order_line_item_id": "127951772415-10087798582227",
            }
        ],
    }

    kwargs = post.call_args.kwargs
    assert kwargs["headers"]["X-EBAY-API-CALL-NAME"] == "GetOrders"
    assert kwargs["headers"]["X-EBAY-API-IAF-TOKEN"] == "test-token"
    assert b"<OrderID>27-15097-79712</OrderID>" in kwargs["data"]


def test_trading_shipment_truth_rejects_different_order(monkeypatch):
    xml = TRADING_XML.replace(b"27-15097-79712", b"99-99999-99999")
    monkeypatch.setattr(readback.requests, "post", Mock(return_value=_response(content=xml)))

    assert readback._trading_shipment_truth(
        access_token="test-token",
        order_id="27-15097-79712",
    ) is None


def test_trading_shipment_truth_fails_on_http_error(monkeypatch):
    monkeypatch.setattr(
        readback.requests,
        "post",
        Mock(return_value=_response(status_code=503, content=b"")),
    )

    try:
        readback._trading_shipment_truth(
            access_token="test-token",
            order_id="27-15097-79712",
        )
    except RuntimeError as exc:
        assert str(exc) == "ebay_trading_get_orders_failed:503"
    else:
        raise AssertionError("Trading HTTP failure must remain visible")


def test_supported_ebay_order_facts_persist_replay_safe_tracking_events(monkeypatch):
    shipment = Mock()
    shipment.id = 225
    candidate = {
        "fulfillment_id": "0504CC67049",
        "tracking_number": "0504CC67049",
        "shipped_at": datetime(2026, 9, 1, 3, 50),
    }

    existing_query = Mock()
    existing_query.filter_by.return_value.first.return_value = None
    monkeypatch.setattr(readback.FBMShipmentTrackingEvent, "query", existing_query)

    added = []
    monkeypatch.setattr(readback.db.session, "add", added.append)

    inserted = readback._persist_ebay_known_tracking_events(
        shipment=shipment,
        candidate=candidate,
        delivered_at=datetime(2026, 9, 3, 11, 57),
    )

    assert inserted == 2
    assert len(added) == 2
    assert added[0].provider == "ebay"
    assert added[0].status == "shipped"
    assert added[0].event_time == datetime(2026, 9, 1, 3, 50)
    assert added[0].raw_event["source"] == "ebay_sell_fulfillment"
    assert added[1].status == "delivered"
    assert added[1].event_time == datetime(2026, 9, 3, 11, 57)
    assert added[1].raw_event["source"] == "ebay_trading_get_orders"


def test_supported_ebay_order_events_do_not_invent_carrier_movement(monkeypatch):
    shipment = Mock()
    shipment.id = 225
    candidate = {
        "fulfillment_id": "87RKL8500193A024",
        "tracking_number": "87RKL8500193A024",
        "shipped_at": datetime(2026, 9, 6, 17, 7, 36),
    }

    existing_query = Mock()
    existing_query.filter_by.return_value.first.return_value = None
    monkeypatch.setattr(readback.FBMShipmentTrackingEvent, "query", existing_query)

    added = []
    monkeypatch.setattr(readback.db.session, "add", added.append)

    readback._persist_ebay_known_tracking_events(
        shipment=shipment,
        candidate=candidate,
        delivered_at=datetime(2026, 9, 9, 8, 9, 49),
    )

    statuses = [event.status for event in added]
    assert statuses == ["shipped", "delivered"]
    assert "accepted" not in statuses
    assert "carrier_accepted" not in statuses
    assert "in_transit" not in statuses
    assert "out_for_delivery" not in statuses
