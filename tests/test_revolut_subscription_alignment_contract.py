from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "services" / "revolut_subscription_alignment.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "services" / "revolut_billing.py").read_text(encoding="utf-8")
BILLING = (ROOT / "templates" / "billing.html").read_text(encoding="utf-8")
ADMIN_PACKAGES = (ROOT / "templates" / "admin" / "packages.html").read_text(encoding="utf-8")
WEBHOOK_SECRET = (ROOT / "templates" / "admin" / "revolut_webhook_secret.html").read_text(encoding="utf-8")
MIGRATION = (ROOT / "migrations" / "manual" / "20260911-revolut-subscription-binding.sql").read_text(encoding="utf-8")


def test_revolut_binding_extends_existing_assignment_not_customer_authority():
    assert 'ForeignKey("account_package_assignments.id", ondelete="CASCADE")' in SERVICE
    assert 'UniqueConstraint("assignment_id", name="uq_revolut_binding_assignment")' in SERVICE
    assert "AccountPackageAssignment.query.filter_by(account_id=account.id).first()" in SERVICE
    assert "assignment.provider_subscription_ref = subscription_ref" in SERVICE
    assert "account.billing_status = \"setup_pending\"" in SERVICE


def test_paid_setup_requires_exact_revolut_plan_variation_and_owner_action():
    assert '@app.post("/billing/revolut/start")' in SERVICE
    assert "not _is_owner(member)" in SERVICE
    assert "package.tier_type != \"paid\"" in SERVICE
    assert 'assignment.billing_provider != "revolut"' in SERVICE
    assert "package.revolut_plan_ref" in SERVICE
    assert "plan_variation_id=str(package.revolut_plan_ref).strip()" in SERVICE
    assert "idempotency_key=f\"bt38-account-{account.id}-package-{package.id}\"" in SERVICE


def test_provider_customer_and_subscription_identity_are_persisted_before_reuse():
    customer_commit = SERVICE.index("binding.customer_ref = customer_ref")
    customer_commit_end = SERVICE.index("db.session.commit()", customer_commit)
    create_subscription = SERVICE.index("client.create_subscription(")
    assert customer_commit < customer_commit_end < create_subscription
    assert "if binding.subscription_ref:" in SERVICE
    assert "client.retrieve_subscription(binding.subscription_ref)" in SERVICE


def test_signed_webhook_resolves_exact_order_subscription_for_setup_and_recurring_cycles():
    assert '@app.post("/webhooks/revolut")' in SERVICE
    assert "verify_revolut_webhook_signature(" in SERVICE
    assert "order = client.retrieve_order(order_ref)" in SERVICE
    assert 'subscription_data.get("subscription_id")' in SERVICE
    assert "query.filter_by(subscription_ref=subscription_ref)" in SERVICE
    assert 'assignment.billing_provider != "revolut"' in SERVICE
    readback = SERVICE.index("subscription = client.retrieve_subscription(binding.subscription_ref)")
    mutation = SERVICE.index("_sync_assignment_from_subscription(assignment, binding, subscription)", readback)
    assert readback < mutation
    assert "subscription identity did not match" in SERVICE
    assert 'return ("", 204)' in SERVICE


def test_revolut_webhook_fails_closed_until_signing_secret_is_in_fly():
    assert 'reason": "webhook_not_configured"' in SERVICE
    assert "except RevolutBillingError:" in SERVICE
    assert "verify_revolut_webhook_signature(" in SERVICE


def test_admin_webhook_provisioning_is_explicit_and_secret_is_not_persisted():
    assert '@app.post("/admin/revolut/webhook/provision")' in SERVICE
    assert "if not _is_admin():" in SERVICE
    assert "client.list_webhooks()" in SERVICE
    assert "client.retrieve_webhook(webhook_id)" in SERVICE
    assert "client.create_webhook(url=target_url, events=list(_WEBHOOK_EVENTS))" in SERVICE
    assert '"ORDER_AUTHORISED", "ORDER_COMPLETED", "ORDER_CANCELLED"' in SERVICE
    assert 'action="/admin/revolut/webhook/provision"' in ADMIN_PACKAGES
    assert "REVOLUT_WEBHOOK_SIGNING_SECRET" in WEBHOOK_SECRET
    assert "signing_secret" not in MIGRATION


def test_revolut_subscription_states_map_to_existing_bt38_billing_statuses():
    assert 'if state == "active":\n        return "active"' in SERVICE
    assert 'if state in {"overdue", "paused"}:\n        return "past_due"' in SERVICE
    assert 'if state in {"cancelled", "finished"}:\n        return "cancelled"' in SERVICE
    assert 'return "setup_pending"' in SERVICE


def test_billing_page_uses_hosted_revolut_setup_not_local_card_capture():
    assert 'action="/billing/revolut/start"' in BILLING
    assert "Continue secure payment setup" in BILLING
    assert "BT38 does not store card or bank credentials" in BILLING
    assert "card_number" not in BILLING
    assert "cvv" not in BILLING.lower()


def test_binding_schema_contains_only_non_secret_provider_identifiers():
    for column in ("customer_ref", "subscription_ref", "setup_order_ref", "provider_state", "last_event"):
        assert column in MIGRATION
    for forbidden in ("secret_key", "signing_secret", "public_key", "card_number", "cvv"):
        assert forbidden not in MIGRATION


def test_revolut_client_remains_lazy_and_uses_fly_environment():
    assert 'REVOLUT_PRODUCTION_API_SECRET_KEY' in CLIENT
    assert 'REVOLUT_MERCHANT_API_VERSION' in CLIENT
    assert 'def configured_revolut_client()' in CLIENT
    assert 'return RevolutMerchantClient(RevolutMerchantConfig.from_environment())' in CLIENT
