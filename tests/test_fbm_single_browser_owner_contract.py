from pathlib import Path


DISPATCH = Path("services/governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")
SMALL = Path("services/governed_fbm_small_alignment.py").read_text(encoding="utf-8")


def test_one_fbm_row_visibility_owner():
    assert "function enforceActiveQueue" not in SMALL
    assert "row.style.display='none'" not in SMALL
    assert "queueMicrotask(enforceActiveQueue)" not in SMALL
    assert "window.addEventListener('load',enforceActiveQueue" not in SMALL
    assert "function render()" in DISPATCH
    assert "renderExistingPager(matched)" in DISPATCH


def test_history_expansion_reuses_canonical_shipping_cost_alignment():
    assert "addCostCell(row,info)" not in DISPATCH
    assert DISPATCH.count("alignCanonicalShippingCost(row,info)") >= 2


def test_duplicate_shipping_fee_filter_is_retired():
    assert "data-fbm-shipping-fees" not in DISPATCH
    assert "shipping_fee_missing" not in DISPATCH
    assert "Shipping fee missing" not in DISPATCH


def test_legacy_lifecycle_browser_state_is_retired():
    assert "legacyTab" not in DISPATCH
    assert "legacySearch" not in DISPATCH
    assert "lifecycleLoadedKey" not in DISPATCH
    assert "bt38_fbm_loaded_" not in DISPATCH
    assert "bt38-fbm-session-rendered" not in DISPATCH


def test_lifecycle_filters_remain_browser_session_only():
    assert "window.BT38FBMApplyCommittedSnapshot=render" in DISPATCH
    assert "button.addEventListener('click',function(){{active=name;currentPage=1;saveSession();render()}})" in DISPATCH
    assert "setInterval(" not in DISPATCH
    assert "X-BT38-FBM-History-Expansion" in DISPATCH
