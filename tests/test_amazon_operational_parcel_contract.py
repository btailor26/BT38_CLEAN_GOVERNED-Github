from pathlib import Path


WRITERS = (
    Path("services/fbm_amazon_order_profile.py"),
    Path("services/governed_amazon_fbm_profile_event_alignment.py"),
    Path("services/governed_amazon_tracking_readback.py"),
)


def test_amazon_operational_state_insert_supplies_required_parcel_without_overwriting_saved_parcel():
    for path in WRITERS:
        source = path.read_text(encoding="utf-8")
        assert "platform, parcel, shipping_service" in source, path
        assert "'amazon','{}'::json,:service" in source, path
        conflict_sql = source.split("ON CONFLICT (store_id, marketplace_order_id) DO UPDATE SET", 1)[1]
        assert "parcel=" not in conflict_sql.split('"""', 1)[0].replace(" ", ""), path
