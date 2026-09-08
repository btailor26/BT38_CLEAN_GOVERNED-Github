from pathlib import Path

from services.governed_order_clarity_alignment import _delivery_days, _cutoff_key


SOURCE = Path("services/governed_order_clarity_alignment.py").read_text(encoding="utf-8")


def test_same_page_shipping_recommendation_is_db_first_and_never_guesses_cutoff():
    assert "FBMRateQuote.query" in SOURCE
    assert "quote.rates" in SOURCE
    assert "fbm_carrier_cutoff:" in SOURCE
    assert "source':'user_confirmed'" in SOURCE
    assert "BT38 never guesses" in SOURCE
    assert "PacklinkAdapter().get_rates" not in SOURCE
    assert "urlopen(" not in SOURCE
    assert "setInterval(" not in SOURCE


def test_shipping_options_only_present_for_parcel_attention_or_change():
    assert "Parcel details required" in SOURCE
    assert "Add / change parcel" in SOURCE
    assert "Change parcel" in SOURCE
    assert ">Recommended shipping</button>" not in SOURCE


def test_saved_rates_are_explicitly_reused_before_refresh():
    assert "Rates not saved" in SOURCE
    assert "Get rates once. BT38 then reuses the saved quote until it expires" in SOURCE
    assert "bt38-get-saved-rates" in SOURCE
    assert "/packlink/rates" in SOURCE


def test_cutoff_entry_requires_user_choice_and_real_time():
    assert "Choose carrier/service" in SOURCE
    assert "For drop-off, confirm it with the shop" in SOURCE
    assert "for collection, use your known collection time" in SOURCE
    assert "type=\"time\"" in SOURCE
    assert _cutoff_key("packlink", "Evri", "Standard Drop Off") == "fbm_carrier_cutoff:packlink|evri|standard drop off"


def test_recommendation_only_uses_delivery_evidence_that_can_be_parsed():
    assert _delivery_days({"delivery": "2 working days"}) == 2
    assert _delivery_days({"delivery": {"transit_days": 1}}) == 1
    assert _delivery_days({"delivery": "unknown"}) is None


def test_paid_label_boundary_is_preserved_inline():
    assert "Payment required before the label is assigned or printable." in SOURCE
    assert "CREATE_PACKLINK_DRAFT" in SOURCE
    assert "Pay in Packlink" in SOURCE
    assert "Check payment / label" in SOURCE
