"""Manual free/paid package catalogue aligned to the existing customer account.

Package definitions are BT38 entitlement/limit authority. CustomerAccount stays the
workspace owner and keeps the existing plan_name/user_limit/billing_status mirrors
used by today's UI and team-seat checks. Revolut remains payment authority for paid
subscriptions; BT38 stores only non-secret provider references and observed status.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hmac
import json
import re
import secrets

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import UniqueConstraint, func

from app import app
from extensions import db
from models import SystemLog, User
from services.account_profile_alignment import CustomerAccount, CustomerAccountMember


class SubscriptionPackage(db.Model):
    __tablename__ = "subscription_packages"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(48), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    tier_type = db.Column(db.String(12), nullable=False, default="free")
    list_price_pence = db.Column(db.Integer, nullable=False, default=0)
    discount_percent = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    price_pence = db.Column(db.Integer, nullable=False, default=0)  # exact amount billed
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    billing_interval = db.Column(db.String(12), nullable=False, default="none")
    user_limit = db.Column(db.Integer, nullable=False, default=1)
    marketplace_limit = db.Column(db.Integer, nullable=True)
    monthly_order_limit = db.Column(db.Integer, nullable=True)
    features = db.Column(db.JSON, nullable=False, default=list)
    revolut_plan_ref = db.Column(db.String(180), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AccountPackageAssignment(db.Model):
    __tablename__ = "account_package_assignments"
    __table_args__ = (UniqueConstraint("account_id", name="uq_account_package_assignment_account"),)
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("customer_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    package_id = db.Column(db.Integer, db.ForeignKey("subscription_packages.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = db.Column(db.String(24), nullable=False, default="active")
    billing_provider = db.Column(db.String(24), nullable=False, default="none")
    provider_subscription_ref = db.Column(db.String(180), nullable=True)
    assigned_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    starts_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ends_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


with app.app_context():
    db.create_all()

_PACKAGE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,47}$")
_TIER_TYPES = {"free", "paid"}
_BILLING_INTERVALS = {"none", "month", "year"}
_ASSIGNMENT_STATUSES = {"setup_pending", "trial", "active", "past_due", "cancelled"}
_BILLING_PROVIDERS = {"none", "manual", "revolut"}
_CSRF_SESSION_KEY = "bt38_package_admin_csrf"


def _is_admin(): return bool(current_user.is_authenticated and str(getattr(current_user, "role", "") or "") == "admin")
def _admin_csrf_token():
    token = str(session.get(_CSRF_SESSION_KEY) or "")
    if not token:
        token = secrets.token_urlsafe(32); session[_CSRF_SESSION_KEY] = token
    return token

def _valid_admin_csrf():
    expected = str(session.get(_CSRF_SESSION_KEY) or ""); submitted = str(request.form.get("csrf_token") or "")
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))
def _package_code(value): return str(value or "").strip().lower().replace(" ", "-")[:48]

def _optional_limit(name, *, maximum):
    raw = str(request.form.get(name) or "").strip()
    if not raw: return None
    value = int(raw)
    if value < 1 or value > maximum: raise ValueError(f"{name} must be between 1 and {maximum}.")
    return value

def _required_limit(name, *, maximum):
    value = int(str(request.form.get(name) or "").strip())
    if value < 1 or value > maximum: raise ValueError(f"{name} must be between 1 and {maximum}.")
    return value

def _price_to_pence(value):
    raw = str(value or "").strip()
    if not raw: return 0
    try: decimal_value = Decimal(raw)
    except InvalidOperation as exc: raise ValueError("Enter a valid package price.") from exc
    if decimal_value < 0 or decimal_value > Decimal("99999.99"): raise ValueError("Package price must be between £0 and £99,999.99.")
    return int((decimal_value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
def _discount_percent(value):
    raw = str(value or "").strip()
    if not raw: return Decimal("0.00")
    try: percent = Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc: raise ValueError("Enter a valid discount percentage.") from exc
    if percent < 0 or percent > 100: raise ValueError("Discount percentage must be between 0 and 100.")
    return percent

def _pricing_from_form(*, tier_type):
    list_price = _price_to_pence(request.form.get("list_price"))
    customer_price = _price_to_pence(request.form.get("price"))
    discount = _discount_percent(request.form.get("discount_percent"))
    if tier_type == "free":
        customer_price = 0
        discount = Decimal("100.00") if list_price > 0 else Decimal("0.00")
        return list_price, discount, customer_price
    if customer_price <= 0: raise ValueError("A paid package needs a customer price above £0.")
    if list_price <= 0: list_price = customer_price
    if customer_price > list_price: raise ValueError("Customer price cannot be above the marked price.")
    calculated = ((Decimal(list_price - customer_price) / Decimal(list_price)) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Customer price is billing authority. Percentage is derived from the exact prices so Revolut never calculates a different amount.
    discount = calculated
    return list_price, discount, customer_price

def _features_from_form():
    values=[]; seen=set()
    for line in str(request.form.get("features") or "").splitlines():
        value=line.strip()[:140]; key=value.casefold()
        if not value or key in seen: continue
        seen.add(key); values.append(value)
        if len(values)>=30: break
    return values

def _money(package):
    if package.tier_type == "free" or int(package.price_pence or 0) <= 0: return "Free"
    amount=Decimal(int(package.price_pence))/Decimal("100"); suffix="/month" if package.billing_interval=="month" else "/year" if package.billing_interval=="year" else ""
    return f"£{amount:.2f}{suffix}"
def _marked_money(package):
    amount=Decimal(int(package.list_price_pence or 0))/Decimal("100"); return f"£{amount:.2f}"
def _log(event,message,details): db.session.add(SystemLog(log_type=event,message=message[:500],details=json.dumps(details,ensure_ascii=False)))


def _package_summary(account_id):
    assignment=AccountPackageAssignment.query.filter_by(account_id=int(account_id)).first()
    if not assignment: return None
    package=db.session.get(SubscriptionPackage,assignment.package_id)
    if not package: return None
    return {"assignment":assignment,"package":package,"name":package.name,"code":package.code,"tier_type":package.tier_type,"marked_price_display":_marked_money(package),"discount_percent":str(package.discount_percent or 0),"price_display":_money(package),"user_limit":package.user_limit,"marketplace_limit":package.marketplace_limit,"monthly_order_limit":package.monthly_order_limit,"features":list(package.features or []),"billing_status":assignment.status,"billing_provider":assignment.billing_provider,"provider_subscription_ref":assignment.provider_subscription_ref}

@app.context_processor
def bt38_package_template_helpers(): return {"bt38_package_for_account":_package_summary}

@app.get("/admin/packages")
@login_required
def bt38_package_admin():
    if not _is_admin(): flash("You do not have permission to manage packages.","danger"); return redirect(url_for("governed.governed_dashboard_page"))
    packages=SubscriptionPackage.query.order_by(SubscriptionPackage.is_active.desc(),SubscriptionPackage.name.asc(),SubscriptionPackage.id.asc()).all(); accounts=CustomerAccount.query.order_by(CustomerAccount.id.asc()).all(); owner_ids=[a.owner_user_id for a in accounts]; owners={u.id:u for u in User.query.filter(User.id.in_(owner_ids)).all()} if owner_ids else {}; assignments={r.account_id:r for r in AccountPackageAssignment.query.all()}; package_by_id={p.id:p for p in packages}; account_rows=[]
    for account in accounts:
        assignment=assignments.get(account.id); account_rows.append({"account":account,"owner":owners.get(account.owner_user_id),"assignment":assignment,"package":package_by_id.get(assignment.package_id) if assignment else None})
    return render_template("admin/packages.html",packages=packages,account_rows=account_rows,csrf_token=_admin_csrf_token(),money=_money,marked_money=_marked_money)

@app.post("/admin/packages/create")
@login_required
def bt38_package_create():
    if not _is_admin(): flash("You do not have permission to manage packages.","danger"); return redirect(url_for("governed.governed_dashboard_page"))
    if not _valid_admin_csrf(): flash("Package update could not be verified. Refresh the page and try again.","danger"); return redirect(url_for("bt38_package_admin"))
    try:
        code=_package_code(request.form.get("code")); name=str(request.form.get("name") or "").strip()[:100]; description=str(request.form.get("description") or "").strip()[:500] or None; tier_type=str(request.form.get("tier_type") or "free").strip().lower(); billing_interval=str(request.form.get("billing_interval") or "none").strip().lower(); user_limit=_required_limit("user_limit",maximum=1000); marketplace_limit=_optional_limit("marketplace_limit",maximum=100); monthly_order_limit=_optional_limit("monthly_order_limit",maximum=100000000); revolut_plan_ref=str(request.form.get("revolut_plan_ref") or "").strip()[:180] or None; features=_features_from_form()
        if not name: raise ValueError("Package name is required.")
        if not _PACKAGE_CODE_RE.fullmatch(code): raise ValueError("Package code must use 2–48 lowercase letters, numbers, dashes or underscores.")
        if tier_type not in _TIER_TYPES: raise ValueError("Choose Free or Paid.")
        if billing_interval not in _BILLING_INTERVALS: raise ValueError("Choose a valid billing interval.")
        if SubscriptionPackage.query.filter_by(code=code).first(): raise ValueError("That package code already exists.")
        list_price_pence,discount_percent,price_pence=_pricing_from_form(tier_type=tier_type)
        if tier_type=="free": billing_interval="none"; revolut_plan_ref=None
        elif billing_interval not in {"month","year"}: raise ValueError("A paid package needs a monthly or yearly billing interval.")
        package=SubscriptionPackage(code=code,name=name,description=description,tier_type=tier_type,list_price_pence=list_price_pence,discount_percent=discount_percent,price_pence=price_pence,currency="GBP",billing_interval=billing_interval,user_limit=user_limit,marketplace_limit=marketplace_limit,monthly_order_limit=monthly_order_limit,features=features,revolut_plan_ref=revolut_plan_ref,is_active=True,created_by_user_id=current_user.id); db.session.add(package); db.session.flush(); _log("package_catalog",f"Package created: {package.name}",{"action":"created","package_id":package.id,"code":package.code,"tier_type":package.tier_type,"list_price_pence":package.list_price_pence,"discount_percent":str(package.discount_percent),"price_pence":package.price_pence,"created_by_user_id":current_user.id}); db.session.commit(); flash(f"Package '{package.name}' created.","success")
    except (TypeError,ValueError) as exc: db.session.rollback(); flash(str(exc),"danger")
    except Exception: db.session.rollback(); app.logger.exception("Package creation failed"); flash("Package could not be created.","danger")
    return redirect(url_for("bt38_package_admin"))

@app.post("/admin/packages/<int:package_id>/update")
@login_required
def bt38_package_update(package_id):
    if not _is_admin(): flash("You do not have permission to manage packages.","danger"); return redirect(url_for("governed.governed_dashboard_page"))
    if not _valid_admin_csrf(): flash("Package update could not be verified. Refresh the page and try again.","danger"); return redirect(url_for("bt38_package_admin"))
    package=db.session.get(SubscriptionPackage,package_id)
    if not package: flash("Package was not found.","danger"); return redirect(url_for("bt38_package_admin"))
    try:
        name=str(request.form.get("name") or "").strip()[:100]; tier_type=str(request.form.get("tier_type") or package.tier_type).strip().lower(); billing_interval=str(request.form.get("billing_interval") or package.billing_interval).strip().lower(); user_limit=_required_limit("user_limit",maximum=1000); marketplace_limit=_optional_limit("marketplace_limit",maximum=100); monthly_order_limit=_optional_limit("monthly_order_limit",maximum=100000000); revolut_plan_ref=str(request.form.get("revolut_plan_ref") or "").strip()[:180] or None
        if not name: raise ValueError("Package name is required.")
        if tier_type not in _TIER_TYPES: raise ValueError("Choose Free or Paid.")
        if billing_interval not in _BILLING_INTERVALS: raise ValueError("Choose a valid billing interval.")
        assigned_account_ids=[r.account_id for r in AccountPackageAssignment.query.filter_by(package_id=package.id).all()]
        if assigned_account_ids and tier_type!=package.tier_type: raise ValueError("Free/Paid type cannot be changed while this package is assigned. Create or choose another package and reassign the customer instead.")
        list_price_pence,discount_percent,price_pence=_pricing_from_form(tier_type=tier_type)
        if tier_type=="free": billing_interval="none"; revolut_plan_ref=None
        elif billing_interval not in {"month","year"}: raise ValueError("A paid package needs a monthly or yearly billing interval.")
        if assigned_account_ids:
            oversized=(db.session.query(CustomerAccountMember.account_id,func.count(CustomerAccountMember.id)).filter(CustomerAccountMember.account_id.in_(assigned_account_ids)).group_by(CustomerAccountMember.account_id).having(func.count(CustomerAccountMember.id)>user_limit).first())
            if oversized: raise ValueError("User limit is below the seats already assigned on a customer using this package.")
        package.name=name; package.description=str(request.form.get("description") or "").strip()[:500] or None; package.tier_type=tier_type; package.list_price_pence=list_price_pence; package.discount_percent=discount_percent; package.price_pence=price_pence; package.billing_interval=billing_interval; package.user_limit=user_limit; package.marketplace_limit=marketplace_limit; package.monthly_order_limit=monthly_order_limit; package.features=_features_from_form(); package.revolut_plan_ref=revolut_plan_ref; package.is_active=request.form.get("is_active")=="on"
        for assignment in AccountPackageAssignment.query.filter_by(package_id=package.id).all():
            account=db.session.get(CustomerAccount,assignment.account_id)
            if account:
                account.plan_name=package.name; account.user_limit=package.user_limit
                if package.tier_type=="free": assignment.status="active"; assignment.billing_provider="none"; assignment.provider_subscription_ref=None; account.billing_status="active"
        _log("package_catalog",f"Package updated: {package.name}",{"action":"updated","package_id":package.id,"code":package.code,"tier_type":package.tier_type,"list_price_pence":package.list_price_pence,"discount_percent":str(package.discount_percent),"price_pence":package.price_pence,"is_active":package.is_active,"updated_by_user_id":current_user.id}); db.session.commit(); flash(f"Package '{package.name}' updated.","success")
    except (TypeError,ValueError) as exc: db.session.rollback(); flash(str(exc),"danger")
    except Exception: db.session.rollback(); app.logger.exception("Package update failed"); flash("Package could not be updated.","danger")
    return redirect(url_for("bt38_package_admin"))

@app.post("/admin/packages/assign")
@login_required
def bt38_package_assign():
    if not _is_admin(): flash("You do not have permission to manage packages.","danger"); return redirect(url_for("governed.governed_dashboard_page"))
    if not _valid_admin_csrf(): flash("Package assignment could not be verified. Refresh the page and try again.","danger"); return redirect(url_for("bt38_package_admin"))
    try:
        account_id=int(request.form.get("account_id") or 0); package_id=int(request.form.get("package_id") or 0); account=db.session.get(CustomerAccount,account_id); package=db.session.get(SubscriptionPackage,package_id)
        if not account: raise ValueError("Customer account was not found.")
        if not package or not package.is_active: raise ValueError("Choose an active package.")
        seat_count=CustomerAccountMember.query.filter_by(account_id=account.id).count()
        if seat_count>int(package.user_limit or 1): raise ValueError(f"This account already has {seat_count} users; '{package.name}' allows {package.user_limit}.")
        status=str(request.form.get("status") or "active").strip().lower(); billing_provider=str(request.form.get("billing_provider") or "none").strip().lower(); provider_subscription_ref=str(request.form.get("provider_subscription_ref") or "").strip()[:180] or None
        if status not in _ASSIGNMENT_STATUSES: raise ValueError("Choose a valid billing status.")
        if billing_provider not in _BILLING_PROVIDERS: raise ValueError("Choose a valid billing provider.")
        if package.tier_type=="free": status="active"; billing_provider="none"; provider_subscription_ref=None
        else:
            if billing_provider=="none": raise ValueError("A paid package needs Manual or Revolut as its billing provider.")
            if billing_provider=="revolut" and status=="active" and not provider_subscription_ref: raise ValueError("An active Revolut package needs its Revolut subscription reference.")
        assignment=AccountPackageAssignment.query.filter_by(account_id=account.id).first(); old_package_id=assignment.package_id if assignment else None
        if not assignment: assignment=AccountPackageAssignment(account_id=account.id,package_id=package.id,assigned_by_user_id=current_user.id,starts_at=datetime.utcnow()); db.session.add(assignment)
        assignment.package_id=package.id; assignment.status=status; assignment.billing_provider=billing_provider; assignment.provider_subscription_ref=provider_subscription_ref; assignment.assigned_by_user_id=current_user.id; assignment.updated_at=datetime.utcnow(); account.plan_name=package.name; account.user_limit=package.user_limit; account.billing_status=status
        _log("package_assignment",f"Package assigned: {package.name}",{"action":"assigned","account_id":account.id,"owner_user_id":account.owner_user_id,"old_package_id":old_package_id,"package_id":package.id,"status":status,"billing_provider":billing_provider,"assigned_by_user_id":current_user.id}); db.session.commit(); flash(f"'{package.name}' assigned to {account.business_name or 'customer account '+str(account.id)}.","success")
    except (TypeError,ValueError) as exc: db.session.rollback(); flash(str(exc),"danger")
    except Exception: db.session.rollback(); app.logger.exception("Package assignment failed"); flash("Package could not be assigned.","danger")
    return redirect(url_for("bt38_package_admin"))
