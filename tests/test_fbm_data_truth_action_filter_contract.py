from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISPATCH = (ROOT / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")
ATTENTION = (ROOT / "services" / "governed_truth_attention_alignment.py").read_text(encoding="utf-8")


def test_data_truth_panel_is_counts_only_and_reuses_visible_fbm_row_truth():
    for key in (
        "source_unverified",
        "tracking_missing",
        "ship_by_missing",
        "delivery_missing",
        "shipping_cost_missing",
        "shipping_fee_missing",
    ):
        assert f'data-bt38-truth-count="{key}"' in ATTENTION
        assert key in DISPATCH

    assert "function rowTruthFlags(row)" in DISPATCH
    assert ".fbm-route-cell" in DISPATCH
    assert ".fbm-promise-line" in DISPATCH
    assert ".fbm-shipping-cost-cell" in DISPATCH
    assert "[data-fbm-shipping-fees" in DISPATCH
    assert "/governed/actions/marketplace/exact-order-recovery-check" not in DISPATCH.split("function rowTruthFlags(row)", 1)[1].split("function refreshTruthSummary", 1)[0]


def test_data_truth_action_filter_sits_with_existing_search_controls_and_reuses_renderer():
    assert "bt38FbmGlobalSearchClear" in DISPATCH
    assert "bt38FbmTruthFilter" in DISPATCH
    assert "clearSearch.insertAdjacentElement('afterend',truthFilterSelect)" in DISPATCH
    assert "truthFilter==='all'||rowTruthFlags(row).indexOf(truthFilter)>=0" in DISPATCH
    assert "truthFilterSelect.addEventListener('change'" in DISPATCH
    assert "selectionAction=readyAction||truthFilter!=='all'" in DISPATCH


def test_data_truth_filter_does_not_add_polling_or_provider_reads():
    truth_filter_section = DISPATCH.split("var truthFilter='all'", 1)[1].split("var historyForm=", 1)[0]
    assert "fetch(" not in truth_filter_section
    assert "setInterval(" not in truth_filter_section
    assert "setTimeout(" not in truth_filter_section
    assert "marketplace" not in truth_filter_section.lower()
    assert "provider" not in truth_filter_section.lower()


def test_recovery_uses_only_explicitly_checked_rows_even_if_working_set_state_changes():
    template = (ROOT / "templates" / "fbm.html").read_text(encoding="utf-8")
    assert "function selectedIds(){return checkboxes.filter(b=>b.checked).map(b=>b.value);}" in template
    assert "if(recoverButton)recoverButton.addEventListener('click'" in template
    assert "const ids=selectedIds();if(!ids.length)return;" in template
    assert "const rows=ids.map(id=>document.querySelector" in template
    assert "exact-order-recovery-check" in template
    assert "selectableCheckboxes().forEach(b=>b.checked=selectAll.checked)" in template
