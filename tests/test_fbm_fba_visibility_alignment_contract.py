from pathlib import Path

FBA = Path("services/governed_fbm_fba_visibility_alignment.py").read_text(encoding="utf-8")
DISPATCH = Path("services/governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")


def test_fba_keeps_original_separate_authority():
    assert "/amazon-fba-stock" in DISPATCH
    assert "addTruthLink(tabBar,'FBA','/amazon-fba-stock'" in DISPATCH
    install = FBA.split("def _install() -> None:", 1)[1]
    assert "addWorkflowButton(tabBar,'fba','FBA')" not in install
    assert "_canonical_fba_rows()" not in install
    assert "_insert_rows(" not in install
    assert "_inject_history_fragment_data =" not in install


def test_fba_visibility_layer_does_not_create_fbm_fba_rows():
    install = FBA.split("def _install() -> None:", 1)[1]
    assert "AmazonFBAInventory" in install
    assert "FBM must not manufacture or own FBA rows" in install
    assert "original_inject(html, payload, fba_count)" in install
