from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = (ROOT / "Dockerfile.current-image-alignment").read_text(encoding="utf-8")
FLY = (ROOT / "fly.toml").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")

BASE_IMAGE = (
    "registry.fly.io/bt38-prod:deployment-01M2BK6REHCGKJQ34796T3WK8P"
    "@sha256:3f7ca913f010fea40a0b8fe20354cae7c010f802328fa0e1eb41258f32168a8b"
)


def test_candidate_reuses_dependencies_but_replaces_application_source_from_exact_head():
    assert f"FROM {BASE_IMAGE}" in OVERLAY
    assert 'dockerfile = "Dockerfile.current-image-alignment"' in FLY
    assert "COPY . /app" in OVERLAY
    assert "! -name '.venv' -exec rm -rf {} +" in OVERLAY
    assert "Application source is replaced completely" in OVERLAY
    assert "accidental runtime authority" in OVERLAY


def test_alignment_layer_does_not_rebuild_dependencies_or_runtime_stack():
    forbidden = (
        "apt-get ",
        "pip install",
        "uv sync",
        "npm install",
        "npm ci",
        "python:3.11-slim",
    )
    for token in forbidden:
        assert token not in OVERLAY


def test_complete_runtime_source_categories_are_not_excluded_from_build_context():
    forbidden_ignores = (
        "services/",
        "templates/",
        "static/",
        "migrations/",
        "scripts/",
        "*.py",
        "*.toml",
    )
    ignored_lines = {
        line.strip()
        for line in DOCKERIGNORE.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert not (ignored_lines & set(forbidden_ignores))


def test_critical_release_files_remain_explicit_fail_fast_copies():
    required = (
        "COPY services/support_notification_alignment.py /app/services/support_notification_alignment.py",
        "COPY services/support_case_alignment.py /app/services/support_case_alignment.py",
        "COPY services/support_attachment_alignment.py /app/services/support_attachment_alignment.py",
        "COPY services/support_monitoring_alignment.py /app/services/support_monitoring_alignment.py",
        "COPY services/cofi_settings_alignment.py /app/services/cofi_settings_alignment.py",
        "COPY services/package_catalog_alignment.py /app/services/package_catalog_alignment.py",
        "COPY services/billing_invoice_alignment.py /app/services/billing_invoice_alignment.py",
        "COPY services/revolut_billing.py /app/services/revolut_billing.py",
        "COPY services/revolut_subscription_alignment.py /app/services/revolut_subscription_alignment.py",
        "COPY templates/admin/packages.html /app/templates/admin/packages.html",
        "COPY migrations/manual/20260911-customer-account-profile.sql /app/migrations/manual/20260911-customer-account-profile.sql",
        "COPY migrations/manual/20260911-package-catalog.sql /app/migrations/manual/20260911-package-catalog.sql",
        "COPY migrations/manual/20260911-revolut-subscription-binding.sql /app/migrations/manual/20260911-revolut-subscription-binding.sql",
        "COPY migrations/manual/20260911-billing-invoices.sql /app/migrations/manual/20260911-billing-invoices.sql",
        "COPY migrations/manual/20260911-support-cases.sql /app/migrations/manual/20260911-support-cases.sql",
        "COPY migrations/manual/20260912-package-pricing-discount.sql /app/migrations/manual/20260912-package-pricing-discount.sql",
        "COPY migrations/manual/20260913-support-case-attachments.sql /app/migrations/manual/20260913-support-case-attachments.sql",
        "COPY scripts/verify_production_db_contract.py /app/scripts/verify_production_db_contract.py",
        "COPY fly.toml /app/fly.toml",
        "COPY Dockerfile.current-image-alignment /app/Dockerfile.current-image-alignment",
    )
    for line in required:
        assert line in OVERLAY


def test_support_startup_fix_remains_in_candidate_runtime_source():
    support = (ROOT / "services" / "support_notification_alignment.py").read_text(encoding="utf-8")
    assert 'if original is None:\n        return False' in support
    assert 'raise RuntimeError("governed notification endpoint is not registered")' not in support
    assert "_install_when_ready()" in support


def test_package_runtime_and_schema_delta_are_carried_together():
    package_service = (ROOT / "services" / "package_catalog_alignment.py").read_text(encoding="utf-8")
    migration = (ROOT / "migrations" / "manual" / "20260912-package-pricing-discount.sql").read_text(encoding="utf-8")
    db_contract = (ROOT / "scripts" / "verify_production_db_contract.py").read_text(encoding="utf-8")
    assert "list_price_pence" in package_service
    assert "discount_percent" in package_service
    assert "ADD COLUMN IF NOT EXISTS list_price_pence" in migration
    assert "ADD COLUMN IF NOT EXISTS discount_percent" in migration
    assert '"subscription_packages"' in db_contract
    assert '"list_price_pence"' in db_contract
    assert '"discount_percent"' in db_contract


def test_revolut_cofi_and_support_runtime_and_schema_are_carried_together():
    db_contract = (ROOT / "scripts" / "verify_production_db_contract.py").read_text(encoding="utf-8")
    attachment_migration = (ROOT / "migrations" / "manual" / "20260913-support-case-attachments.sql").read_text(encoding="utf-8")
    for source_path in (
        "services/cofi_settings_alignment.py",
        "services/revolut_billing.py",
        "services/revolut_subscription_alignment.py",
        "services/billing_invoice_alignment.py",
        "services/support_case_alignment.py",
        "services/support_attachment_alignment.py",
        "services/support_monitoring_alignment.py",
        "services/support_notification_alignment.py",
    ):
        assert (ROOT / source_path).is_file()
    for table in (
        '"system_config"',
        '"revolut_subscription_bindings"',
        '"billing_invoices"',
        '"support_cases"',
        '"support_case_messages"',
        '"support_case_attachments"',
    ):
        assert table in db_contract
    assert "CREATE TABLE IF NOT EXISTS support_case_attachments" in attachment_migration
