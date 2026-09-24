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
