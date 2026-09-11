from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mcf_has_its_own_existing_fbm_workspace_area():
    source = (ROOT / "services" / "governed_fbm_mcf_visibility_alignment.py").read_text()

    assert '"queue": "mcf"' in source
    assert "addWorkflowButton(tabBar,'mcf','MCF');" in source
    assert "data-fbm-mcf-readonly=\"1\"" in source
    assert "MarketplaceOrder.mcf_order_id.in_(mcf_ids)" in source
    assert "MCFOrder" in source


def test_mcf_rows_cannot_fall_into_fba_pending_presentation():
    source = (ROOT / "services" / "governed_fbm_mcf_visibility_alignment.py").read_text()

    assert "if _is_mcf_marketplace_row(row):" in source
    assert "return None" in source
    assert 'item_id.startswith("MCF-")' in source
    assert "fba_visibility._queue_for = mcf_safe_fba_queue_for" in source


def test_mcf_area_is_presentation_only_and_zero_polling():
    source = (ROOT / "services" / "governed_fbm_mcf_visibility_alignment.py").read_text()

    assert "setInterval" not in source
    assert "while True" not in source
    assert "requests." not in source
    assert "create_fulfillment_order" not in source
    assert "db.session.commit" not in source
