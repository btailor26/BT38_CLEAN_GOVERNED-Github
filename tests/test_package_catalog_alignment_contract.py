from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _compact(source: str) -> str:
    """Ignore formatting-only whitespace in source-level contract assertions."""
    return "".join(source.split())


def test_package_catalog_is_loaded_from_existing_app_startup():
    main = _read("main.py")
    assert "import services.account_profile_alignment" in main
    assert "import services.package_catalog_alignment" in main


def test_package_catalog_keeps_existing_customer_account_as_workspace_authority():
    source = _read("services/package_catalog_alignment.py")
    compact = _compact(source)
    assert "from services.account_profile_alignment import CustomerAccount, CustomerAccountMember" in source
    assert 'account.plan_name=package.name' in compact
    assert 'account.user_limit=package.user_limit' in compact
    assert 'account.billing_status=status' in compact
    assert "class SubscriptionPackage" in source
    assert "class AccountPackageAssignment" in source


def test_free_and_paid_tiers_and_revolut_reference_are_explicit():
    source = _read("services/package_catalog_alignment.py")
    compact = _compact(source)
    assert '_TIER_TYPES={"free","paid"}' in compact
    assert 'revolut_plan_ref=db.Column' in compact
    assert 'billing_provider=db.Column' in compact
    assert 'provider_subscription_ref=db.Column' in compact
    assert 'ifpackage.tier_type=="free":' in compact
    assert 'billing_provider=="revolut"' in compact


def test_assigned_package_cannot_silently_change_free_paid_authority():
    source = _read("services/package_catalog_alignment.py")
    compact = _compact(source)
    assert "ifassigned_account_idsandtier_type!=package.tier_type:" in compact
    assert "Free/Paid type cannot be changed while this package is assigned." in source
    assert "reassign the customer instead" in source


def test_package_limits_and_features_are_manual_admin_fields():
    source = _read("services/package_catalog_alignment.py")
    template = _read("templates/admin/packages.html")
    for field in ("user_limit", "marketplace_limit", "monthly_order_limit", "features"):
        assert field in source
        assert f'name="{field}"' in template
    assert '/admin/packages/create' in source
    assert '/admin/packages/assign' in source


def test_package_schema_has_explicit_manual_migration_and_db_guards():
    migration = _read("migrations/manual/20260911-package-catalog.sql")
    assert "CREATE TABLE IF NOT EXISTS subscription_packages" in migration
    assert "CREATE TABLE IF NOT EXISTS account_package_assignments" in migration
    assert "uq_account_package_assignment_account" in migration
    assert "ck_subscription_packages_free_shape" in migration
    assert "ck_subscription_packages_paid_shape" in migration
    assert "billing_provider IN ('none', 'manual', 'revolut')" in migration


def test_billing_page_reads_package_without_global_page_query():
    source = _read("services/package_catalog_alignment.py")
    compact = _compact(source)
    billing = _read("templates/billing.html")
    assert 'return{"bt38_package_for_account":_package_summary}' in compact
    assert 'bt38_package_for_account(account.id)' in billing
    assert "Normal BT38 pages pay no DB" in source
    assert "BT38 controls package entitlement, billing history and billing documents." in billing
    assert "class SubscriptionPackage" not in billing
    assert "class AccountPackageAssignment" not in billing
