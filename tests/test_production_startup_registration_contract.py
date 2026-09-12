from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "services" / "package_catalog_alignment.py").read_text(encoding="utf-8")
INVOICE = (ROOT / "services" / "billing_invoice_alignment.py").read_text(encoding="utf-8")
REVOLUT = (ROOT / "services" / "revolut_subscription_alignment.py").read_text(encoding="utf-8")
SUPPORT_CASE = (ROOT / "services" / "support_case_alignment.py").read_text(encoding="utf-8")
SUPPORT_ATTACHMENT = (ROOT / "services" / "support_attachment_alignment.py").read_text(encoding="utf-8")
SUPPORT_MONITOR = (ROOT / "services" / "support_monitoring_alignment.py").read_text(encoding="utf-8")
SUPPORT_NOTIFICATION = (ROOT / "services" / "support_notification_alignment.py").read_text(encoding="utf-8")


def _position(text: str, needle: str) -> int:
    position = text.find(needle)
    assert position >= 0, f"missing startup dependency marker: {needle}"
    return position


def test_app_bound_service_registration_order_is_dependency_safe():
    package = _position(INIT, "import services.package_catalog_alignment")
    invoice = _position(INIT, "import services.billing_invoice_alignment")
    revolut = _position(INIT, "import services.revolut_subscription_alignment")
    support_case = _position(INIT, "import services.support_case_alignment")
    support_attachment = _position(INIT, "import services.support_attachment_alignment")
    support_monitor = _position(INIT, "import services.support_monitoring_alignment")
    support_notification = _position(INIT, "import services.support_notification_alignment")

    assert package < invoice < revolut
    assert revolut < support_case < support_attachment < support_monitor < support_notification


def test_package_tables_are_declared_before_invoice_foreign_keys_can_be_created():
    assert 'class SubscriptionPackage(db.Model):' in PACKAGE
    assert '__tablename__ = "subscription_packages"' in PACKAGE
    assert 'class AccountPackageAssignment(db.Model):' in PACKAGE
    assert '__tablename__ = "account_package_assignments"' in PACKAGE

    assert 'db.ForeignKey("account_package_assignments.id"' in INVOICE
    assert 'db.ForeignKey("subscription_packages.id"' in INVOICE
    assert _position(INIT, "import services.package_catalog_alignment") < _position(
        INIT, "import services.billing_invoice_alignment"
    )


def test_revolut_model_registration_uses_already_registered_package_authority():
    assert (
        "from services.package_catalog_alignment import "
        "AccountPackageAssignment, SubscriptionPackage, _is_admin"
    ) in REVOLUT
    assert "from services.billing_invoice_alignment import record_completed_revolut_invoice" in REVOLUT
    assert _position(INIT, "import services.billing_invoice_alignment") < _position(
        INIT, "import services.revolut_subscription_alignment"
    )


def test_support_registration_chain_does_not_require_bell_route_during_import():
    assert 'endpoint = "governed.governed_ui_notifications"' in SUPPORT_NOTIFICATION
    assert "original = app.view_functions.get(endpoint)" in SUPPORT_NOTIFICATION
    assert 'if original is None:\n        return False' in SUPPORT_NOTIFICATION
    assert 'raise RuntimeError("governed notification endpoint is not registered")' not in SUPPORT_NOTIFICATION
    assert "def _install_when_ready() -> None:" in SUPPORT_NOTIFICATION
    assert "@app.before_request" in SUPPORT_NOTIFICATION
    assert "_bt38_support_notification_install_deferred" in SUPPORT_NOTIFICATION


def test_support_dependencies_are_declared_before_the_notification_extension():
    assert "class SupportCase(db.Model):" in SUPPORT_CASE
    assert "class SupportCaseAttachment(db.Model):" in SUPPORT_ATTACHMENT
    assert "SupportCase" in SUPPORT_MONITOR
    assert "SupportCaseMessage" in SUPPORT_NOTIFICATION
    assert _position(INIT, "import services.support_case_alignment") < _position(
        INIT, "import services.support_notification_alignment"
    )


def test_startup_modules_do_not_call_payment_provider_during_import():
    package_prefix = PACKAGE.split("@app.get", 1)[0]
    invoice_prefix = INVOICE.split("@app.get", 1)[0]
    revolut_prefix = REVOLUT.split("@app.context_processor", 1)[0]

    for source in (package_prefix, invoice_prefix, revolut_prefix):
        assert "configured_revolut_client()" not in source
        assert ".create_customer(" not in source
        assert ".create_subscription(" not in source
        assert ".retrieve_subscription(" not in source
        assert ".retrieve_order(" not in source
