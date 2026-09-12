from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "services" / "revolut_subscription_alignment.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "services" / "revolut_billing.py").read_text(encoding="utf-8")
BILLING = (ROOT / "templates" / "billing.html").read_text(encoding="utf-8")
ADMIN_PACKAGES = (ROOT / "templates" / "admin" / "packages.html").read_text(encoding="utf-8")
WEBHOOK_SECRET = (ROOT / "templates" / "admin" / "revolut_webhook_secret.html").read_text(encoding="utf-8")
MIGRATION = (ROOT / "migrations" / "manual" / "20260911-revolut-subscription-binding.sql").read_text(encoding="utf-8")


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def test_revolut_binding_extends_existing_assignment_not_customer_authority():
    compact = _compact(SERVICE)
    assert 'ForeignKey("account_package_assignments.id",ondelete="CASCADE")' in compact
    assert 'UniqueConstraint("assignment_id",name="uq_revolut_binding_assignment")' in compact
    assert "AccountPackageAssignment.query.filter_by(account_id=account.id).first()" in SERVICE
    assert "assignment.provider_subscription_ref=binding.subscription_ref" in compact or "assignment.provider_subscription_ref=subref" in compact
    assert 'account.billing_status="setup_pending"' in compact


def test_paid_setup_requires_exact_revolut_plan_variation_and_owner_action():
    compact = _compact(SERVICE)
    assert '@app.post("/billing/revolut/start")' in SERVICE
    assert "not_is_owner(member)" in compact
    assert 'package.tier_type!="paid"' in compact
    assert 'assignment.billing_provider!="revolut"' in compact
    assert "package.revolut_plan_ref" in SERVICE
    assert "plan_variation_id=str(package.revolut_plan_ref).strip()" in compact
    assert 'idempotency_key=f"bt38-account-{account.id}-package-{package.id}"' in compact


def test_provider_customer_and_subscription_identity_are_persisted_before_reuse():
    compact = _compact(SERVICE)
    customer_commit = compact.index("binding.customer_ref=ref;db.session.commit()")
    create_subscription = compact.index("client.create_subscription(")
    assert customer_commit < create_subscription
    assert "ifbinding.subscription_ref:" in compact
    assert "client.retrieve_subscription(binding.subscription_ref)" in compact


def test_signed_webhook_resolves_exact_order_subscription_for_setup_and_recurring_cycles():
    compact = _compact(SERVICE)
    assert '@app.post("/webhooks/revolut")' in SERVICE
    assert "verify_revolut_webhook_signature(" in SERVICE
    assert "order=client.retrieve_order(order_ref)" in compact
    assert 'sd=order.get("subscription_data")' in compact
    assert 'sd.get("subscription_id")' in compact
    assert "RevolutSubscriptionBinding.query.filter_by(subscription_ref=subref).first()" in SERVICE
    assert 'assignment.billing_provider!="revolut"' in compact
    readback = compact.index("subscription=client.retrieve_subscription(binding.subscription_ref)")
    mutation = compact.index("_sync_assignment(assignment,binding,subscription)", readback)
    assert readback < mutation
    assert "subscription identity did not match" in SERVICE
    assert 'return("",204)' in compact


def test_revolut_webhook_fails_closed_until_signing_secret_is_in_fly():
    compact = _compact(SERVICE)
    assert 'reason":"webhook_not_configured"' in compact
    assert "exceptRevolutBillingError:" in compact
    assert "verify_revolut_webhook_signature(" in SERVICE


def test_admin_webhook_provisioning_is_explicit_and_secret_is_not_persisted():
    compact = _compact(SERVICE)
    assert '@app.post("/admin/revolut/webhook/provision")' in SERVICE
    assert "ifnot_is_admin():" in compact
    assert "client.list_webhooks()" in SERVICE
    assert "client.retrieve_webhook(wid)" in compact
    assert "client.create_webhook(url=target,events=list(_WEBHOOK_EVENTS))" in compact
    assert '"ORDER_AUTHORISED","ORDER_COMPLETED","ORDER_CANCELLED"' in compact
    assert 'action="/admin/revolut/webhook/provision"' in ADMIN_PACKAGES
    assert "REVOLUT_WEBHOOK_SIGNING_SECRET" in WEBHOOK_SECRET
    assert "signing_secret" not in MIGRATION


def test_revolut_subscription_states_map_to_existing_bt38_billing_statuses():
    compact = _compact(SERVICE)
    assert 'ifstate=="active":return"active"' in compact
    assert 'ifstatein{"overdue","paused"}:return"past_due"' in compact
    assert 'ifstatein{"cancelled","finished"}:return"cancelled"' in compact
    assert 'return"setup_pending"' in compact


def test_billing_page_uses_hosted_revolut_setup_not_local_card_capture():
    assert 'action="/billing/revolut/start"' in BILLING
    assert "Continue to payment" in BILLING
    assert "BT38 does not store card, bank or wallet credentials" in BILLING
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
