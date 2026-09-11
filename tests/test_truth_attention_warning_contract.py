from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_truth_attention_is_warning_and_review_only():
    source = _source("services/governed_truth_attention_alignment.py")

    assert "Needs admin attention" in source
    assert "admin_truth_review_request" in source
    assert "/governed/actions/admin-truth-review-request" in source
    assert "SystemEvent(" in source
    assert '"truth_mutation_started": False' in source
    assert '"marketplace_write_started": False' in source
    assert '"provider_write_started": False' in source
    assert '"inventory_mutation_started": False' in source

    # This layer may write the review/audit event only. It must not become a
    # second order, shipment, inventory, provider or marketplace authority.
    for forbidden in (
        "MarketplaceOrder(",
        "MCFOrder(",
        "FBMShipment(",
        "WarehouseStock(",
        "submit_governed_marketplace_action(",
        "requests.post(",
        "requests.put(",
        "setInterval(",
    ):
        assert forbidden not in source


def test_known_unresolved_truth_areas_are_explicitly_marked():
    source = _source("services/governed_truth_attention_alignment.py")

    for section in (
        "Marketplace order quantity",
        "SKU / item identity",
        "Shipment timestamp",
        "Destination / parcel facts",
        "MCF order quantity / items",
        "MCF destination",
        "MCF declared value",
        "MCF actual charges",
    ):
        assert section in source

    assert "Request admin review" in source
    assert "BT38 is explicitly marking unresolved areas instead of treating defaults as verified facts." in source
    assert "Admin review requested." in source


def test_obvious_missing_fbm_truth_gets_row_warning_without_fabrication():
    source = _source("services/governed_truth_attention_alignment.py")

    assert "markObviousUnknowns" in source
    assert "Quantity is missing or not proven" in source
    assert "SKU or marketplace item identity is incomplete" in source
    assert "Marketplace lifecycle says shipped but parcel tracking evidence is not present" in source
    assert "Parcel facts are under review" in source
    assert "Amazon order identity has not yet been confirmed" in source


def test_services_package_installs_truth_attention_after_existing_mcf_projection():
    package_source = _source("services/__init__.py")

    mcf_index = package_source.index("import services.governed_fbm_mcf_visibility_alignment")
    warning_index = package_source.index("import services.governed_truth_attention_alignment")
    assert mcf_index < warning_index
