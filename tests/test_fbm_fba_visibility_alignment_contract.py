from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = (ROOT / "services" / "governed_fbm_fba_visibility_alignment.py").read_text(encoding="utf-8")
SERVICES_INIT = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")
DISPATCH = (ROOT / "services" / "governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")


def test_fba_visibility_is_installed_without_replacing_fbm_shipping_eligibility():
    assert "import services.governed_fbm_fba_visibility_alignment" in SERVICES_INIT
    assert "dispatch_queue._inject = aligned_inject" in ALIGNMENT
    assert "_workspace_fbm_eligible" not in ALIGNMENT
    assert "shipping_options" not in ALIGNMENT


def test_fba_pending_and_dispatched_have_only_the_requested_local_queues():
    assert 'if status == "pending":\n        return "pending"' in ALIGNMENT
    assert 'return "fba"' in ALIGNMENT
    assert '"shipped"' in ALIGNMENT
    assert '"dispatched"' in ALIGNMENT
    assert '"delivered"' in ALIGNMENT
    assert 'addWorkflowButton(tabBar,\'fba\',\'FBA\');' in ALIGNMENT


def test_fba_rows_are_explicitly_read_only():
    assert 'data-fbm-fba-readonly="1"' in ALIGNMENT
    assert "Fulfilment by Amazon" in ALIGNMENT
    assert ">Read only<" in ALIGNMENT
    assert "fbm-shipping-options" not in ALIGNMENT
    assert "fbm-order-checkbox" not in ALIGNMENT


def test_alignment_reads_db_only_and_does_not_create_inventory_or_marketplace_work():
    assert "MarketplaceOrder" in ALIGNMENT
    assert "joinedload" in ALIGNMENT
    for forbidden in (
        "get_inventory(",
        "get_orders(",
        "requests.get(",
        "requests.post(",
        "notify_governed_runtime_work",
        "AmazonFBAInventory",
        "WarehouseStock",
        "db.session.commit",
        "db.session.add",
        "setattr(",
    ):
        assert forbidden not in ALIGNMENT


def test_history_fragment_preserves_read_only_fba_visibility():
    source = Path("services/governed_fbm_fba_visibility_alignment.py").read_text(encoding="utf-8")
    assert "original_history_fragment_inject = dispatch_queue._inject_history_fragment_data" in source
    assert "def aligned_history_fragment_inject(html, payload):" in source
    history = source.split("def aligned_history_fragment_inject(html, payload):", 1)[1].split(
        "def aligned_inject(html, payload, _fba_count):", 1
    )[0]
    assert "_insert_rows(html, _canonical_fba_rows())" in history
    assert "next_payload.update(fba_payload)" in history
    assert "original_history_fragment_inject(html, next_payload)" in history
    assert "dispatch_queue._inject_history_fragment_data = aligned_history_fragment_inject" in source


def test_fba_is_registered_in_current_cached_browser_owner():
    # The current FBM controller owns cached lifecycle counts and row lists.
    # FBA must join those exact caches, including the reset performed whenever
    # History is recomputed, rather than patching the retired `var result` shape.
    assert "var result={ready_dispatch:0" not in ALIGNMENT
    assert (
        '"var cachedCounts={ready_dispatch:0,pending:0,dispatched:0,cancelled:0,replacements:0,refunds:0};"'
        in ALIGNMENT
    )
    assert (
        '"var cachedRowsByQueue={ready_dispatch:[],pending:[],dispatched:[],cancelled:[],replacements:[],refunds:[]};"'
        in ALIGNMENT
    )
    assert (
        '"var cachedCounts={ready_dispatch:0,pending:0,dispatched:0,cancelled:0,fba:0,replacements:0,refunds:0};"'
        in ALIGNMENT
    )
    assert (
        '"var cachedRowsByQueue={ready_dispatch:[],pending:[],dispatched:[],cancelled:[],fba:[],replacements:[],refunds:[]};"'
        in ALIGNMENT
    )
    # Both cache declarations occur twice in the current owner: initial build
    # and refreshHistoryMatches reset. Unbounded str.replace must align both.
    assert DISPATCH.count(
        "var cachedCounts={ready_dispatch:0,pending:0,dispatched:0,cancelled:0,replacements:0,refunds:0};"
    ) == 2
    assert DISPATCH.count(
        "var cachedRowsByQueue={ready_dispatch:[],pending:[],dispatched:[],cancelled:[],replacements:[],refunds:[]};"
    ) == 2
    assert "addWorkflowButton(tabBar,'fba','FBA');" in DISPATCH
    assert "/amazon-fba-stock" not in DISPATCH
    assert "/amazon-fba-stock" not in ALIGNMENT


def test_fba_tab_authority_is_locked_local_and_cannot_be_replaced_by_navigation():
    # Permanent authority boundary: the FBM FBA control is a local workflow tab.
    # Neither the base controller nor compatibility alignment may turn it into
    # a front-end/back-end route, redirect, link, or stock-page replacement.
    assert "addWorkflowButton(tabBar,'fba','FBA');" in DISPATCH
    assert "addTruthLink(tabBar,'FBA'" not in DISPATCH
    assert "addTruthLink(tabBar,'FBA'" not in ALIGNMENT
    for forbidden in (
        "/amazon-fba-stock",
        "/governed/amazon-fba-stock",
        "window.location",
        "location.href",
    ):
        assert forbidden not in ALIGNMENT
