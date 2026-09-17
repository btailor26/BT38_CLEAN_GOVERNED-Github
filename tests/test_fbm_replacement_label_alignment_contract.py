from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = (ROOT / "fbm_models.py").read_text(encoding="utf-8")
ALIGNMENT = (ROOT / "services" / "governed_fbm_replacement_label_alignment.py").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static" / "js" / "fbm_replacement_label_alignment.js").read_text(encoding="utf-8")
QZ = (ROOT / "static" / "js" / "fbm_qz_print.js").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_replacement_reason_is_persisted_on_existing_fbm_shipment_authority():
    assert "replacement_reason_code" in MODEL
    assert "replacement_reason = db.Column(db.Text" in MODEL
    assert "replacement_reason_recorded_at" in MODEL
    assert "replacement_reason_recorded_by" in MODEL
    assert "FBMShipment" in ALIGNMENT
    assert "ALTER TABLE fbm_shipments" in ALIGNMENT
    assert "CREATE TABLE" not in ALIGNMENT


def test_replacement_label_requires_dispatched_original_and_explicit_reason():
    assert "Replacement labels are only available after the original order has been dispatched" in ALIGNMENT
    assert "_completed_original_exists" in ALIGNMENT
    assert "shipment_purpose" in ALIGNMENT
    assert 'purpose != "replacement"' in ALIGNMENT
    assert "replacement_reason_code" in ALIGNMENT
    assert "State the reason for this replacement label purchase" in ALIGNMENT
    assert "REPLACEMENT_REASON_CODES" in ALIGNMENT


def test_replacement_reuses_existing_packlink_path_without_background_purchase():
    assert 'endpoint = "governed_fbm.packlink_create_draft"' in ALIGNMENT
    assert "return current(*args, **kwargs)" in ALIGNMENT
    assert "PacklinkAdapter" not in ALIGNMENT
    assert "AmazonShippingAdapter" not in ALIGNMENT
    assert "purchase_shipment" not in ALIGNMENT


def test_dispatched_workspace_places_replacement_beside_manual_shipping():
    assert "Replacement label" in SCRIPT
    assert "bt38-replacement-route" in SCRIPT
    assert "bt38-replacement-start" in SCRIPT
    assert 'provider-action[data-provider="manual"]' in SCRIPT
    assert "insertAdjacentHTML('afterend'" in SCRIPT
    assert "rowIsDispatched" in SCRIPT
    assert "Why is another label being purchased?" in SCRIPT
    assert "label_damaged" in SCRIPT
    assert "parcel_damaged" in SCRIPT
    assert "customer_replacement" in SCRIPT
    assert "shipment_purpose = 'replacement'" in SCRIPT
    assert "confirm_additional_shipment = 'CONFIRM_REPLACEMENT'" in SCRIPT


def test_dispatched_reprint_reuses_existing_packlink_label_action_without_parallel_path():
    assert "preservePacklinkAuthority" in SCRIPT
    assert ".packlink-existing-status[data-shipment-id]" in SCRIPT
    assert "button.hidden = true" in SCRIPT
    assert "button.remove()" not in SCRIPT.split("function preservePacklinkAuthority", 1)[1].split("function activeWorkflowTab", 1)[0]
    assert "bulkPacklinkLabels" in SCRIPT
    assert "Reprint Label" in SCRIPT
    assert "dispatchedPacklinkLabelAction" in SCRIPT
    assert "duplicate.remove()" in SCRIPT
    assert "packlinkStatus(item.shipmentId)" in QZ
    assert "/fbm/shipments/${encodeURIComponent(shipmentId)}/packlink/status" in QZ
    assert "packlink/draft" not in SCRIPT.split("function alignDispatchedReprintAction", 1)[1].split("function replacementRouteHtml", 1)[0]


def test_dispatched_selection_is_restored_only_for_existing_selected_action_bar():
    assert "active === 'dispatched'" in SCRIPT
    assert "active === 'ready_dispatch'" in SCRIPT
    assert "selectAll.disabled = !(ready || dispatched)" in SCRIPT
    assert "row.dataset.fbmQueue" in SCRIPT
    assert "checkbox.disabled = !selectable" in SCRIPT
    assert "requestAnimationFrame(alignDispatchedReprintAction)" in SCRIPT
    assert "setInterval" not in SCRIPT


def test_amazon_native_second_purchase_is_not_faked_for_dispatched_replacement():
    assert "amazon_buy_shipping" in SCRIPT
    assert "Amazon native replacement unavailable" in SCRIPT
    assert "Choose an eligible external carrier" in SCRIPT


def test_replacement_alignment_is_installed_in_governed_runtime():
    assert "install_governed_fbm_replacement_label_alignment" in MAIN
    assert "existing Packlink/FBMShipment path" in MAIN