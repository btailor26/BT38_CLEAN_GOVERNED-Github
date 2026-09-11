from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = (ROOT / "services" / "support_case_alignment.py").read_text()
CASES = (ROOT / "templates" / "support_cases.html").read_text()
CASE = (ROOT / "templates" / "support_case.html").read_text()
PUBLIC = (ROOT / "templates" / "support.html").read_text()
SERVICES = (ROOT / "services" / "__init__.py").read_text()


def test_support_categories_cover_real_bt38_failure_surfaces():
    for category in (
        '"new_integration"',
        '"marketplace_connection"',
        '"billing"',
        '"shipping"',
        '"orders"',
        '"inventory"',
        '"product_linking"',
        '"listings"',
        '"sync_runtime"',
        '"users_access"',
        '"data_review"',
        '"reporting"',
        '"feature_request"',
    ):
        assert category in SUPPORT


def test_support_is_case_id_based_and_account_scoped():
    assert '__tablename__ = "support_cases"' in SUPPORT
    assert '__tablename__ = "support_case_messages"' in SUPPORT
    assert 'account_id = db.Column' in SUPPORT
    assert 'BT38-{stamp}-{int(case.id):06d}' in SUPPORT
    assert 'int(case.account_id) != int(account.id)' in SUPPORT
    assert 'SupportCase.query.filter_by(account_id=account.id)' in SUPPORT


def test_public_support_page_is_preserved_and_case_centre_has_separate_routes():
    assert '<h1 class="mt-3 text-4xl font-black">Support</h1>' in PUBLIC
    assert 'Apply to Try BT38 Inventory' in PUBLIC
    assert 'Open Support Centre' in PUBLIC
    assert 'href="/support/cases"' in PUBLIC
    assert '@app.get("/support")' not in SUPPORT
    assert '@app.get("/support/cases")' in SUPPORT
    assert '@app.post("/support/cases/new")' in SUPPORT
    assert '@app.route("/support/cases/<case_id>"' in SUPPORT
    assert '@app.get("/admin/support/cases")' in SUPPORT


def test_case_workflow_has_customer_reply_and_admin_state_control():
    assert 'waiting_customer' in SUPPORT
    assert 'in_progress' in SUPPORT
    assert 'resolved' in SUPPORT
    assert 'closed' in SUPPORT
    assert 'SupportCaseMessage(' in SUPPORT
    assert 'author_role="admin" if _is_admin() else "customer"' in SUPPORT
    assert '/admin/support/cases/{{ case.case_id }}/state' in CASE
    assert 'Case conversation' in CASE


def test_support_centre_warns_against_secret_submission():
    warning = 'Do not paste passwords, API secrets, card numbers or private keys.'
    assert warning in CASES
    assert 'Do not include passwords, API secrets, card numbers or private keys.' in CASE


def test_support_module_does_not_create_marketplace_provider_or_inventory_actions():
    forbidden = (
        'requests.',
        'configured_revolut_client',
        'amazon_client',
        'ebay_client',
        'push_quantity',
        'propagate_quantity',
        'MarketplaceOrder.query',
        'WarehouseStock.query',
    )
    for token in forbidden:
        assert token not in SUPPORT


def test_support_is_installed_in_existing_services_package():
    assert 'import services.support_case_alignment' in SERVICES
    assert 'href="/support/cases"' in SUPPORT


def test_case_ui_exposes_case_id_category_priority_status_and_history():
    assert 'Every issue is tracked against a BT38 Case ID' in CASES
    for text in ('Case ID', 'Category', 'Priority', 'Status', 'Your support cases'):
        assert text in CASES
    for text in ('Case ID', 'Case status', 'Last updated', 'Description'):
        assert text in CASE
