from inspect import getsource

from services.fbm_packlink_draft_alignment import (
    _browser_save_body,
    _strip_non_contract_address_selectors,
    install_packlink_draft_alignment,
)


def test_packlink_address_selectors_stay_out_of_provider_address_dto():
    body = {
        "to": {
            "name": "Karen",
            "surname": "Llewellyn",
            "street1": "Landscape Cottage, Primrose Hill",
            "city": "Gateshead",
            "zip_code": "NE9 5XP",
            "country": "GB",
            "country_code": "GB",
            "postal_zone_id": "gb-zone",
            "zip_code_id": "pc_ne95xp",
        },
        "additional_data": {
            "postal_zone_id_to": "gb-zone",
            "zip_code_id_to": "pc_ne95xp",
        },
    }

    returned = _strip_non_contract_address_selectors(body)

    assert returned is body
    assert body["to"]["country"] == "GB"
    assert "country_code" not in body["to"]
    assert "postal_zone_id" not in body["to"]
    assert "zip_code_id" not in body["to"]
    assert body["additional_data"]["postal_zone_id_to"] == "gb-zone"
    assert body["additional_data"]["zip_code_id_to"] == "pc_ne95xp"


def test_browser_save_body_preserves_provider_selector_authority_in_additional_data():
    snapshot = {
        "shipment": {
            "from": {"name": "BT38", "street1": "1 Test Rd", "city": "Leicester", "zip_code": "LE1 1AA", "country": "GB"},
            "to": {"name": "Karen", "street1": "Landscape Cottage", "city": "Gateshead", "zip_code": "NE9 5XP", "country": "GB"},
            "packages": [{"id": "parcel-1", "weight": 1}],
            "additional_data": {
                "postal_zone_id_to": "gb-zone",
                "zip_code_id_to": "pc_ne95xp",
            },
        }
    }

    body = _browser_save_body(snapshot, "BT38-REF")

    assert body["packlink_reference"] == "BT38-REF"
    assert body["to"]["country"] == "GB"
    assert body["to"]["state"] == "United Kingdom"
    assert body["additional_data"]["postal_zone_id_to"] == "gb-zone"
    assert body["additional_data"]["zip_code_id_to"] == "pc_ne95xp"


def test_packlink_alignment_keeps_one_create_path_then_provider_browser_save_readback():
    source = getsource(install_packlink_draft_alignment)

    assert "original_create_draft" in source
    assert 'normalized_endpoint == "shipments"' in source
    assert "_strip_non_contract_address_selectors(body)" in source
    assert "self.get_shipment(reference)" in source
    assert "_browser_save_body(snapshot, reference)" in source
    assert 'self._put_json(f"shipments/{reference}", save_body)' in source
    assert "provider_auto_saved" in source
    assert "provider_saved_complete" in source
