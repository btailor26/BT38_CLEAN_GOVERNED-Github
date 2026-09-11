"""Bind Revolut Merchant subscription state to the existing BT38 package assignment.

The existing CustomerAccount remains workspace authority and AccountPackageAssignment
remains entitlement authority. This module stores only provider-side identifiers in a
1:1 extension row and performs provider writes only after an explicit owner/admin action.
"""
from __future__ import annotations

from datetime import datetime
import json
import secrets

from flask import jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import UniqueConstraint

from app import app
from extensions import db
from models import SystemLog, User
from services.account_profile_alignment import UserProfile, _account_for_user, _is_owner
from services.package_catalog_alignment import AccountPackageAssignment, SubscriptionPackage, _is_admin
from services.billing_invoice_alignment import record_completed_revolut_invoice
from services.revolut_billing import RevolutBillingError, configured_revolut_client, verify_revolut_webhook_signature


class RevolutSubscriptionBinding(db.Model):
    __tablename__ = "revolut_subscription_bindings"
    __table_args__ = (UniqueConstraint("assignment_id", name="uq_revolut_binding_assignment"), UniqueConstraint("subscription_ref", name="uq_revolut_binding_subscription"))
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("account_package_assignments.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    customer_ref = db.Column(db.String(180), nullable=True, index=True)
    subscription_ref = db.Column(db.String(180), nullable=True, unique=True, index=True)
    setup_order_ref = db.Column(db.String(180), nullable=True, index=True)
    provider_state = db.Column(db.String(40), nullable=True)
    last_event = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

with app.app_context(): db.create_all()

_BILLING_CSRF_KEY = "bt38_revolut_billing_csrf"
_ADMIN_WEBHOOK_CSRF_KEY = "bt38_revolut_webhook_admin_csrf"
_WEBHOOK_EVENTS = ["ORDER_AUTHORISED", "ORDER_COMPLETED", "ORDER_CANCELLED"]

def _token(key):
    value = str(session.get(key) or "")
    if not value:
        value = secrets.token_urlsafe(32); session[key] = value
    return value

def _valid(key):
    supplied = str(request.form.get("csrf_token") or ""); expected = str(session.get(key) or "")
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))

def _binding_for_assignment(assignment_id):
    row = RevolutSubscriptionBinding.query.filter_by(assignment_id=int(assignment_id)).first()
    if row: return row
    row = RevolutSubscriptionBinding(assignment_id=int(assignment_id)); db.session.add(row); db.session.flush(); return row

def _owner_identity(account):
    owner = db.session.get(User, int(account.owner_user_id))
    if not owner or not str(owner.email or "").strip(): raise ValueError("The paying account owner needs an email address before Revolut setup can start.")
    profile = db.session.get(UserProfile, int(owner.id))
    name = str(getattr(profile, "display_name", "") or owner.username or account.business_name or "").strip()
    if not name: raise ValueError("The paying account owner needs a name before Revolut setup can start.")
    return name[:140], str(owner.email).strip().lower()[:120]

def _assignment_for_owner():
    account, member = _account_for_user(current_user.id)
    if not account or not _is_owner(member): raise PermissionError
    assignment = AccountPackageAssignment.query.filter_by(account_id=account.id).first()
    if not assignment: raise ValueError("Assign a BT38 package before starting payment setup.")
    package = db.session.get(SubscriptionPackage, assignment.package_id)
    if not package or not package.is_active: raise ValueError("The assigned package is not active.")
    if package.tier_type != "paid" or assignment.billing_provider != "revolut": raise ValueError("This package does not use Revolut billing.")
    if not str(package.revolut_plan_ref or "").strip(): raise ValueError("This paid package needs its Revolut plan variation ID before payment setup can start.")
    return account, assignment, package

def _map_provider_state(state):
    state = str(state or "").strip().lower()
    if state == "active": return "active"
    if state in {"overdue", "paused"}: return "past_due"
    if state in {"cancelled", "finished"}: return "cancelled"
    return "setup_pending"

def _sync_assignment(assignment, binding, payload):
    state = str(payload.get("state") or "").strip().lower(); binding.provider_state = state or binding.provider_state; assignment.status = _map_provider_state(state)
    from services.account_profile_alignment import CustomerAccount
    account = db.session.get(CustomerAccount, assignment.account_id)
    if account: account.billing_status = assignment.status

def _audit(event, message, details): db.session.add(SystemLog(log_type=event, message=message[:500], details=json.dumps(details, ensure_ascii=False)))

@app.context_processor
def bt38_revolut_billing_context(): return {"bt38_revolut_billing_csrf": lambda: _token(_BILLING_CSRF_KEY), "bt38_revolut_webhook_admin_csrf": lambda: _token(_ADMIN_WEBHOOK_CSRF_KEY)}

@app.post("/billing/revolut/start")
@login_required
def bt38_revolut_subscription_start():
    if not _valid(_BILLING_CSRF_KEY): return redirect(url_for("bt38_billing_page"))
    try:
        account, assignment, package = _assignment_for_owner(); binding = _binding_for_assignment(assignment.id); client = configured_revolut_client()
        if not binding.customer_ref:
            name, email = _owner_identity(account); customer = client.create_customer(full_name=name, email=email); ref = str(customer.get("id") or "").strip()
            if not ref: raise RevolutBillingError("Revolut did not return a customer ID.")
            binding.customer_ref = ref; db.session.commit()
        if binding.subscription_ref:
            subscription = client.retrieve_subscription(binding.subscription_ref); _sync_assignment(assignment, binding, subscription); assignment.provider_subscription_ref = binding.subscription_ref; db.session.commit()
        else:
            subscription = client.create_subscription(plan_variation_id=str(package.revolut_plan_ref).strip(), customer_id=str(binding.customer_ref).strip(), setup_order_redirect_url=url_for("bt38_billing_page", _external=True), external_reference=f"bt38-account-{account.id}", idempotency_key=f"bt38-account-{account.id}-package-{package.id}")
            subref = str(subscription.get("id") or "").strip(); orderref = str(subscription.get("setup_order_id") or "").strip()
            if not subref or not orderref: raise RevolutBillingError("Revolut did not return the subscription setup identifiers.")
            binding.subscription_ref=subref; binding.setup_order_ref=orderref; binding.provider_state=str(subscription.get("state") or "pending")[:40]; assignment.provider_subscription_ref=subref; assignment.status="setup_pending"; account.billing_status="setup_pending"; db.session.commit()
        if assignment.status == "active": return redirect(url_for("bt38_billing_page"))
        order = client.retrieve_order(binding.setup_order_ref); checkout_url = str(order.get("checkout_url") or "").strip()
        if not checkout_url.startswith("https://"): raise RevolutBillingError("Revolut did not return a secure hosted checkout URL.")
        return redirect(checkout_url)
    except PermissionError: return redirect(url_for("bt38_profile_page"))
    except (ValueError, RevolutBillingError) as exc:
        db.session.rollback(); app.logger.warning("Revolut billing setup blocked: %s", str(exc)); return redirect(url_for("bt38_billing_page"))
    except Exception:
        db.session.rollback(); app.logger.exception("Revolut billing setup failed"); return redirect(url_for("bt38_billing_page"))

@app.post("/admin/revolut/webhook/provision")
@login_required
def bt38_revolut_webhook_provision():
    if not _is_admin(): return redirect(url_for("governed.governed_dashboard_page"))
    if not _valid(_ADMIN_WEBHOOK_CSRF_KEY): return redirect(url_for("bt38_package_admin"))
    try:
        target = url_for("bt38_revolut_webhook", _external=True)
        if not target.startswith("https://"): raise RevolutBillingError("Revolut webhook URL must use HTTPS.")
        client=configured_revolut_client(); listing=client.list_webhooks(); rows=listing.get("webhooks",[]) if isinstance(listing,dict) else []
        exact=next((r for r in rows if isinstance(r,dict) and str(r.get("url") or "").rstrip("/")==target.rstrip("/")),None); created=False
        if exact:
            wid=str(exact.get("id") or "").strip()
            if not wid: raise RevolutBillingError("Existing Revolut webhook did not include an ID.")
            webhook=client.retrieve_webhook(wid)
        else: webhook=client.create_webhook(url=target, events=list(_WEBHOOK_EVENTS)); created=True
        wid=str(webhook.get("id") or "").strip(); secret=str(webhook.get("signing_secret") or "").strip()
        if not wid or not secret: raise RevolutBillingError("Revolut did not return the webhook signing secret.")
        return render_template("admin/revolut_webhook_secret.html", webhook_id=wid, webhook_url=str(webhook.get("url") or target), events=list(webhook.get("events") or []), signing_secret=secret, created=created)
    except RevolutBillingError as exc:
        return render_template("admin/revolut_webhook_secret.html", error=str(exc), webhook_id="", webhook_url="", events=[], signing_secret="", created=False),503

@app.post("/webhooks/revolut")
def bt38_revolut_webhook():
    raw=request.get_data(cache=True,as_text=False)
    try: valid=verify_revolut_webhook_signature(raw_body=raw,timestamp_header=request.headers.get("Revolut-Request-Timestamp",""),signature_header=request.headers.get("Revolut-Signature",""))
    except RevolutBillingError: return jsonify({"ok":False,"reason":"webhook_not_configured"}),503
    if not valid: return jsonify({"ok":False,"reason":"invalid_signature"}),401
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): return jsonify({"ok":False,"reason":"invalid_payload"}),400
    event=str(payload.get("event") or "").strip()[:80]; order_ref=str(payload.get("order_id") or "").strip()
    if not event or not order_ref: return ("",204)
    try:
        client=configured_revolut_client(); order=client.retrieve_order(order_ref)
        # Exact readback identity must agree with the signed event before any invoice/account mutation.
        if str(order.get("id") or "").strip() != order_ref: raise RevolutBillingError("Revolut order identity did not match the signed webhook order.")
        sd=order.get("subscription_data") if isinstance(order,dict) else None; subref=str(sd.get("subscription_id") or "").strip() if isinstance(sd,dict) else ""
        if not subref: return ("",204)
        binding=RevolutSubscriptionBinding.query.filter_by(subscription_ref=subref).first()
        if not binding: return ("",204)
        assignment=db.session.get(AccountPackageAssignment,binding.assignment_id)
        if not assignment or assignment.billing_provider!="revolut": return ("",204)
        package=db.session.get(SubscriptionPackage,assignment.package_id)
        from services.account_profile_alignment import CustomerAccount
        account=db.session.get(CustomerAccount,assignment.account_id)
        if not package or not account: raise RevolutBillingError("BT38 billing authority is incomplete for this subscription.")
        subscription=client.retrieve_subscription(binding.subscription_ref)
        if str(subscription.get("id") or "").strip()!=str(binding.subscription_ref): raise RevolutBillingError("Revolut subscription identity did not match the persisted binding.")
        _sync_assignment(assignment,binding,subscription); assignment.provider_subscription_ref=binding.subscription_ref; binding.last_event=event
        # Invoice only exact provider-completed money. Package price is never substituted for payment truth.
        record_completed_revolut_invoice(account=account,assignment=assignment,package=package,order=order,subscription_ref=binding.subscription_ref)
        _audit("revolut_webhook","Revolut subscription/payment state verified",{"event":event,"assignment_id":assignment.id,"subscription_ref":binding.subscription_ref,"provider_state":binding.provider_state,"billing_status":assignment.status,"order_ref":order_ref})
        db.session.commit()
    except (RevolutBillingError,ValueError):
        db.session.rollback(); app.logger.exception("Revolut exact order/subscription billing readback failed"); return jsonify({"ok":False,"reason":"provider_readback_failed"}),503
    return ("",204)
