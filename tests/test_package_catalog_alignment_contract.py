from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_package_catalog_is_loaded_from_existing_app_startup():
    main = _read("main.py")
    assert "import services.account_profile_alignment" in main
    assert "import services.package_catalog_alignment" in main


def test_package_catalog_keeps_existing_customer_account_as_workspace_authority():
    source = _read("services/package_catalog_alignment.py")
    assert "from services.account_profile_alignment import CustomerAccount, CustomerAccountMember" in source
    assert 'account.plan_name = package.name' in source
    assert 'account.user_limit = package.user_limit' in source
    assert 'account.billing_status = status' in source
    assert "class SubscriptionPackage" in source
    assert "class AccountPackageAssignment" in source


def test_free_and_paid_tiers_and_revolut_reference_are_explicit():
    source = _read("services/package_catalog_alignment.py")
    assert '_TIER_TYPES = {"free", "paid"}' in source
    assert 'revolut_plan_ref = db.Column' in source
    assert 'billing_provider = db.Column' in source
    assert 'provider_subscription_ref = db.Column' in source
    assert 'if package.tier_type == "free":' in source
    assert 'billing_provider == "revolut"' in source


def test_package_limits_and_features_are_manual_admin_fields():
    source = _read("services/package_catalog_alignment.py")
    template = _read("templates/admin/packages.html")
    for field in ("user_limit", "marketplace_limit", "monthly_order_limit", "features"):
        assert field in source
        assert f'name="{field}"' in template
    assert '/admin/packages/create' in source
    assert '/admin/packages/assign' in source


def test_billing_page_reads_package_without_global_page_query():
    source = _read("services/package_catalog_alignment.py")
    billing = _read("templates/billing.html")
    assert 'return {"bt38_package_for_account": _package_summary}' in source
    assert 'bt38_package_for_account(account.id)' in billing
    assert "Normal BT38 pages pay no DB" in source
