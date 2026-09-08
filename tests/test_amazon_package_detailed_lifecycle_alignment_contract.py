from services.governed_amazon_tracking_readback import _package_lifecycle, _package_truth


def test_detailed_out_for_delivery_promotes_in_transit_package_status():
    lifecycle, detailed = _package_lifecycle({
        "packageStatus": {
            "status": "IN_TRANSIT",
            "detailedStatus": "OUT_FOR_DELIVERY",
        }
    })
    assert lifecycle == "out_for_delivery"
    assert detailed == "OUT_FOR_DELIVERY"


def test_package_truth_uses_more_specific_detailed_lifecycle_without_inventing_history():
    truth, ambiguity = _package_truth({
        "orderId": "204-9540786-1929166",
        "fulfillment": {"status": "IN_TRANSIT"},
        "packages": [{
            "packageReferenceId": "447550145",
            "trackingNumber": "T00TNA6517711147",
            "carrier": "Hermes UK",
            "shippingService": "Hermes Standard - Drop Off",
            "packageStatus": {
                "status": "IN_TRANSIT",
                "detailedStatus": "OUT_FOR_DELIVERY",
            },
        }],
    })

    assert ambiguity is None
    assert truth is not None
    assert truth["package_status"] == "IN_TRANSIT"
    assert truth["package_detailed_status"] == "OUT_FOR_DELIVERY"
    assert truth["lifecycle_status"] == "out_for_delivery"


def test_detailed_status_does_not_override_protected_cancelled_lifecycle():
    lifecycle, detailed = _package_lifecycle({
        "packageStatus": {
            "status": "CANCELLED",
            "detailedStatus": "OUT_FOR_DELIVERY",
        }
    })
    assert lifecycle == "cancelled"
    assert detailed == "OUT_FOR_DELIVERY"
