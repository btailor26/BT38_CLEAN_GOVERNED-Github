"""Bind Revolut Merchant subscription state to the existing BT38 package assignment.

The existing CustomerAccount remains workspace authority and AccountPackageAssignment
remains entitlement authority. This module stores only provider-side identifiers in a
1:1 extension row and performs provider writes only after an explicit owner action.
"""
from __future__ import annotations

from datetime import datetime
import json
import secrets

from flask import jsonify, redirect, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import UniqueConstraint

from app import app
from extensions import db
from models import SystemLog, User
from services.account_profile_alignment import (
    UserProfile,
    _account_for_user,
    _is_owner,
)
from services.package_catalog_alignment import (
    AccountPackageAssignment,
    SubscriptionPackage,
)
from services.revolut_billing import (
    RevolutBillingError,
    configured_revolut_client,
    verify_revolut_webhook_signature,
)


class RevolutSubscriptionBinding(db.Model):
    """Provider metadata only; never a second package/account authority."""

    __tablename__ = "revolut_subscription_bindings"
    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_revolut_binding_assignment"),
        UniqueConstraint("subscription_ref", name="uq_revolut_binding_subscription"),
    )

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer,
        db.ForeignKey("account_package_assignments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    customer_ref = db.Column(db.String(180), nullable=True, index=True)
    subscription_ref = db.Column(db.String(180), nullable=True, unique=True, index=True)
    setup_order_ref = db.Column(db.String(180), nullable=True, index=True)
    provider_state = db.Column(db.String(40), nullable=True)
    last_event = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


with app.app_context():
    db.create_all()


_BILLING_CSRF_KEY = "bt38_revolut_billing_csrf"


def _csrf_token() -> str:
    token = str(session.get(_BILLING_CSRF_KEY) or "")
    if not token:
        token = secrets.token_urlsafe(32)
        session[_BILLING_CSRF_KEY] = token
    return token


def _valid_csrf() -> bool:
    supplied = str(request.form.get("csrf_token") or "")
    expected = str(session.get(_BILLING_CSRF_KEY) or "")
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def _binding_for_assignment(assignment_id: int) -> RevolutSubscriptionBinding:
    row = RevolutSubscriptionBinding.query.filter_by(assignment_id=int(assignment_id)).first()
    if row:
        return row
    row = RevolutSubscriptionBinding(assignment_id=int(assignment_id))
    db.session.add(row)
    db.session.flush()
    return row


def _owner_identity(account) -> tuple[str, str]:
    owner = db.session.get(User, int(account.owner_user_id))
    if not owner or not str(owner.email or "").strip():
        raise ValueError("The paying account owner needs an email address before Revolut setup can start.")
    profile = db.session.get(UserProfile, int(owner.id))
    full_name = str(getattr(profile, "display_name", "") or owner.username or account.business_name or "").strip()
    if not full_name:
        raise ValueError("The paying account owner needs a name before Revolut setup can start.")
    return full_name[:140], str(owner.email).strip().lower()[:120]


def _assignment_for_owner():
    account, member = _account_for_user(current_user.id)
    if not account or not _is_owner(member):
        raise PermissionError("Billing is available to the paying account owner.")
    assignment = AccountPackageAssignment.query.filter_by(account_id=account.id).first()
    if not assignment:
        raise ValueError("Assign a BT38 package before starting payment setup.")
    package = db.session.get(SubscriptionPackage, assignment.package_id)
    if not package or not package.is_active:
        raise ValueError("The assigned package is not active.")
    if package.tier_type != "paid" or assignment.billing_provider != "revolut":
        raise ValueError("This package does not use Revolut billing.")
    if not str(package.revolut_plan_ref or "").strip():
        raise ValueError("This paid package needs its Revolut plan variation ID before payment setup can start.")
    return account, assignment, package


def _map_provider_state(state: str) -> str:
    state = str(state or "").strip().lower()
    if state == "active":
        return "active"
    if state in {"overdue", "paused"}:
        return "past_due"
    if state in {"cancelled", "finished"}:
        return "cancelled"
    return "setup_pending"


def _sync_assignment_from_subscription(assignment, binding, payload: dict) -> None:
    state = str(payload.get("state") or "").strip().lower()
    binding.provider_state = state or binding.provider_state
    assignment.status = _map_provider_state(state)
    account = assignment and db.session.get(
        __import__("services.account_profile_alignment", fromlist=["CustomerAccount"]).CustomerAccount,
        assignment.account_id,
    )
    if account:
        account.billing_status = assignment.status


def _audit(event: str, message: str, details: dict) -> None:
    db.session.add(SystemLog(
        log_type=event,
        message=message[:500],
        details=json.dumps(details, ensure_ascii=False),
    ))


@app.context_processor
def bt38_revolut_billing_context():
    return {
        "bt38_revolut_billing_csrf": _csrf_token,
    }


@app.post("/billing/revolut/start")
@login_required
def bt38_revolut_subscription_start():
    if not _valid_csrf():
        return redirect(url_for("bt38_billing_page"))

    try:
        account, assignment, package = _assignment_for_owner()
        binding = _binding_for_assignment(assignment.id)
        client = configured_revolut_client()

        # Revolut documents that customer creation does not deduplicate by email.
        # Therefore the returned customer ID is committed before any subscription
        # write. Subsequent attempts always reuse that exact customer.
        if not binding.customer_ref:
            full_name, email = _owner_identity(account)
            customer = client.create_customer(full_name=full_name, email=email)
            customer_ref = str(customer.get("id") or "").strip()
            if not customer_ref:
                raise RevolutBillingError("Revolut did not return a customer ID.")
            binding.customer_ref = customer_ref
            db.session.commit()

        # Existing subscription authority always wins. Never create a parallel
        # subscription just because setup is resumed or a browser retries.
        if binding.subscription_ref:
            subscription = client.retrieve_subscription(binding.subscription_ref)
            _sync_assignment_from_subscription(assignment, binding, subscription)
            assignment.provider_subscription_ref = binding.subscription_ref
            db.session.commit()
        else:
            subscription = client.create_subscription(
                plan_variation_id=str(package.revolut_plan_ref).strip(),
                customer_id=str(binding.customer_ref).strip(),
                setup_order_redirect_url=url_for("bt38_billing_page", _external=True),
                external_reference=f"bt38-account-{account.id}",
                idempotency_key=f"bt38-account-{account.id}-package-{package.id}",
            )
            subscription_ref = str(subscription.get("id") or "").strip()
            setup_order_ref = str(subscription.get("setup_order_id") or "").strip()
            if not subscription_ref or not setup_order_ref:
                raise RevolutBillingError("Revolut did not return the subscription setup identifiers.")
            binding.subscription_ref = subscription_ref
            binding.setup_order_ref = setup_order_ref
            binding.provider_state = str(subscription.get("state") or "pending")[:40]
            assignment.provider_subscription_ref = subscription_ref
            assignment.status = "setup_pending"
            account.billing_status = "setup_pending"
            _audit("revolut_subscription", "Revolut subscription setup created", {
                "account_id": account.id,
                "assignment_id": assignment.id,
                "package_id": package.id,
                "subscription_ref": subscription_ref,
                "setup_order_ref": setup_order_ref,
            })
            db.session.commit()

        if assignment.status == "active":
            return redirect(url_for("bt38_billing_page"))

        if not binding.setup_order_ref:
            raise RevolutBillingError("Revolut subscription is pending but has no setup order reference.")
        order = client.retrieve_order(binding.setup_order_ref)
        checkout_url = str(order.get("checkout_url") or "").strip()
        if not checkout_url.startswith("https://"):
            raise RevolutBillingError("Revolut did not return a secure hosted checkout URL.")
        return redirect(checkout_url)

    except PermissionError:
        return redirect(url_for("bt38_profile_page"))
    except (ValueError, RevolutBillingError) as exc:
        db.session.rollback()
        app.logger.warning("Revolut billing setup blocked: %s", str(exc))
        return redirect(url_for("bt38_billing_page"))
    except Exception:
        db.session.rollback()
        app.logger.exception("Revolut billing setup failed")
        return redirect(url_for("bt38_billing_page"))


@app.post("/webhooks/revolut")
def bt38_revolut_webhook():
    raw_body = request.get_data(cache=True, as_text=False)
    if not verify_revolut_webhook_signature(
        raw_body=raw_body,
        timestamp_header=request.headers.get("Revolut-Request-Timestamp", ""),
        signature_header=request.headers.get("Revolut-Signature", ""),
    ):
        return jsonify({"ok": False, "reason": "invalid_signature"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "reason": "invalid_payload"}), 400

    event = str(payload.get("event") or "").strip()[:80]
    order_ref = str(payload.get("order_id") or "").strip()
    if not event or not order_ref:
        return jsonify({"ok": True, "status": "ignored"}), 200

    binding = RevolutSubscriptionBinding.query.filter_by(setup_order_ref=order_ref).first()
    if not binding or not binding.subscription_ref:
        # Do not mutate any customer from an unknown provider event.
        return jsonify({"ok": True, "status": "unmatched"}), 200

    assignment = db.session.get(AccountPackageAssignment, binding.assignment_id)
    if not assignment or assignment.billing_provider != "revolut":
        return jsonify({"ok": True, "status": "unmatched"}), 200

    try:
        subscription = configured_revolut_client().retrieve_subscription(binding.subscription_ref)
        if str(subscription.get("id") or "").strip() != str(binding.subscription_ref):
            raise RevolutBillingError("Revolut subscription identity did not match the persisted binding.")
        _sync_assignment_from_subscription(assignment, binding, subscription)
        assignment.provider_subscription_ref = binding.subscription_ref
        binding.last_event = event
        _audit("revolut_webhook", "Revolut subscription state verified", {
            "event": event,
            "assignment_id": assignment.id,
            "subscription_ref": binding.subscription_ref,
            "provider_state": binding.provider_state,
            "billing_status": assignment.status,
        })
        db.session.commit()
    except RevolutBillingError:
        db.session.rollback()
        app.logger.exception("Revolut exact subscription readback failed after signed webhook")
        return jsonify({"ok": False, "reason": "provider_readback_failed"}), 503

    return jsonify({"ok": True, "status": "verified"}), 200
