"""BT38 customer support cases using the existing customer account authority.

Support is an account-scoped workflow only. It does not call marketplaces,
payment providers, carriers, or mutate inventory/order truth.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import app
from extensions import db
from services.account_profile_alignment import _account_for_user


SUPPORT_CATEGORIES = (
    ("new_integration", "New integration / API connection", "Connect a new marketplace, WMS, website, carrier or external system."),
    ("marketplace_connection", "Marketplace connection / authorisation", "Amazon, eBay or another marketplace will not connect, authorise, refresh or receive events."),
    ("billing", "Billing / subscription / payment", "Package, payment, recurring billing, invoice, plan or account billing issue."),
    ("shipping", "Shipping / tracking / labels", "Carrier, label, tracking, dispatch, parcel, shipping cost or delivery evidence issue."),
    ("orders", "Orders / FBM / FBA / MCF", "Order import, fulfilment classification, MCF creation, status or order lifecycle issue."),
    ("inventory", "Inventory / warehouse / stock", "Warehouse quantity, stock authority, stock movement or inventory visibility issue."),
    ("product_linking", "Product Linking", "SKU relationship, group linking, unlinking or governed quantity propagation issue."),
    ("listings", "Listings / imports / marketplace data", "Listing import, missing listing, suppression, SKU/item identity or catalogue issue."),
    ("sync_runtime", "Sync / webhook / runtime", "Governed sync, webhook, scheduler, event, retry or runtime processing issue."),
    ("users_access", "Users / login / permissions", "Login, owner/team access, permissions, seats or profile issue."),
    ("data_review", "Data review / audit", "Something is under review, uncertain, inconsistent or marked Needs admin attention."),
    ("reporting", "Reporting / exports / data", "Dashboard figures, reports, CSV, financial evidence or exported data issue."),
    ("feature_request", "Feature / development request", "Request a BT38 feature, workflow change or development assessment."),
    ("other", "Other", "Anything that does not fit another support category."),
)
_CATEGORY_MAP = {key: label for key, label, _ in SUPPORT_CATEGORIES}
_VALID_STATUS = {"open", "in_progress", "waiting_customer", "resolved", "closed"}
_VALID_PRIORITY = {"low", "normal", "high", "urgent"}


class SupportCase(db.Model):
    __tablename__ = "support_cases"
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.String(40), unique=True, nullable=True, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("customer_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    opened_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False, index=True)
    subject = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="normal", index=True)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    affected_area = db.Column(db.String(160))
    source_page = db.Column(db.String(240))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class SupportCaseMessage(db.Model):
    __tablename__ = "support_case_messages"
    id = db.Column(db.Integer, primary_key=True)
    case_pk = db.Column(db.Integer, db.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    author_role = db.Column(db.String(20), nullable=False, default="customer")
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


with app.app_context():
    db.create_all()


def _is_admin() -> bool:
    return str(getattr(current_user, "role", "") or "").strip().lower() == "admin"


def _clean(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _customer_scope():
    account, member = _account_for_user(current_user.id)
    return account, member


def _case_or_404(case_id: str) -> SupportCase:
    case = SupportCase.query.filter_by(case_id=str(case_id or "").strip().upper()).first()
    if case is None:
        abort(404)
    if not _is_admin():
        account, _ = _customer_scope()
        if account is None or int(case.account_id) != int(account.id):
            abort(404)
    return case


def _case_number(case: SupportCase) -> str:
    stamp = (case.created_at or datetime.utcnow()).strftime("%y%m%d")
    return f"BT38-{stamp}-{int(case.id):06d}"


def _status_label(value: str) -> str:
    return {
        "open": "Open",
        "in_progress": "In progress",
        "waiting_customer": "Waiting for customer",
        "resolved": "Resolved",
        "closed": "Closed",
    }.get(value, value.replace("_", " ").title())


@app.context_processor
def bt38_support_context():
    return {
        "support_categories": SUPPORT_CATEGORIES,
        "support_category_labels": _CATEGORY_MAP,
        "support_status_label": _status_label,
    }


@app.get("/support")
@login_required
def bt38_support_page():
    account, _ = _customer_scope()
    if account is None and not _is_admin():
        flash("Your BT38 account is not available yet.", "warning")
        return redirect(url_for("bt38_profile_page"))
    if _is_admin() and request.args.get("all") == "1":
        cases = SupportCase.query.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc()).limit(500).all()
    else:
        if account is None:
            cases = []
        else:
            cases = (SupportCase.query.filter_by(account_id=account.id)
                     .order_by(SupportCase.updated_at.desc(), SupportCase.id.desc()).limit(250).all())
    return render_template("support.html", cases=cases, account=account, admin_view=False)


@app.post("/support/cases")
@login_required
def bt38_support_create_case():
    account, _ = _customer_scope()
    if account is None:
        flash("A customer account is required to open a support case.", "danger")
        return redirect(url_for("bt38_support_page"))
    category = _clean(request.form.get("category"), 50).lower()
    subject = _clean(request.form.get("subject"), 180)
    description = _clean(request.form.get("description"), 8000)
    priority = _clean(request.form.get("priority"), 20).lower() or "normal"
    affected_area = _clean(request.form.get("affected_area"), 160)
    source_page = _clean(request.form.get("source_page"), 240) or _clean(request.referrer, 240)
    if category not in _CATEGORY_MAP:
        flash("Choose a valid support category.", "danger")
        return redirect(url_for("bt38_support_page"))
    if priority not in _VALID_PRIORITY:
        priority = "normal"
    if not subject or not description:
        flash("Add a subject and describe what is happening.", "danger")
        return redirect(url_for("bt38_support_page"))
    case = SupportCase(
        account_id=account.id,
        opened_by_user_id=current_user.id,
        category=category,
        subject=subject,
        description=description,
        priority=priority,
        status="open",
        affected_area=affected_area or None,
        source_page=source_page or None,
    )
    db.session.add(case)
    db.session.flush()
    case.case_id = _case_number(case)
    db.session.commit()
    flash(f"Support case {case.case_id} has been opened.", "success")
    return redirect(url_for("bt38_support_case_page", case_id=case.case_id))


@app.route("/support/cases/<case_id>", methods=["GET", "POST"])
@login_required
def bt38_support_case_page(case_id):
    case = _case_or_404(case_id)
    if request.method == "POST":
        body = _clean(request.form.get("message"), 8000)
        if not body:
            flash("Enter a message before sending.", "danger")
            return redirect(url_for("bt38_support_case_page", case_id=case.case_id))
        db.session.add(SupportCaseMessage(
            case_pk=case.id,
            author_user_id=current_user.id,
            author_role="admin" if _is_admin() else "customer",
            body=body,
        ))
        if not _is_admin() and case.status in {"resolved", "waiting_customer"}:
            case.status = "open"
        elif _is_admin() and case.status == "open":
            case.status = "in_progress"
        case.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Reply added to the case.", "success")
        return redirect(url_for("bt38_support_case_page", case_id=case.case_id))
    messages = (SupportCaseMessage.query.filter_by(case_pk=case.id)
                .order_by(SupportCaseMessage.created_at.asc(), SupportCaseMessage.id.asc()).all())
    return render_template("support_case.html", case=case, messages=messages, is_support_admin=_is_admin())


@app.get("/admin/support")
@login_required
def bt38_admin_support_page():
    if not _is_admin():
        abort(403)
    status = _clean(request.args.get("status"), 30).lower()
    query = SupportCase.query
    if status in _VALID_STATUS:
        query = query.filter_by(status=status)
    cases = query.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc()).limit(500).all()
    counts = {state: SupportCase.query.filter_by(status=state).count() for state in _VALID_STATUS}
    return render_template("support.html", cases=cases, account=None, admin_view=True, support_counts=counts, selected_status=status)


@app.post("/admin/support/cases/<case_id>/state")
@login_required
def bt38_admin_support_case_state(case_id):
    if not _is_admin():
        abort(403)
    case = _case_or_404(case_id)
    status = _clean(request.form.get("status"), 30).lower()
    priority = _clean(request.form.get("priority"), 20).lower()
    if status in _VALID_STATUS:
        case.status = status
    if priority in _VALID_PRIORITY:
        case.priority = priority
    case.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"{case.case_id} updated.", "success")
    return redirect(url_for("bt38_support_case_page", case_id=case.case_id))


def _install_support_navigation() -> None:
    if getattr(app, "_bt38_support_nav_installed", False):
        return

    @app.after_request
    def bt38_support_navigation(response):
        try:
            if response.status_code != 200 or "text/html" not in str(response.content_type or "").lower():
                return response
            html = response.get_data(as_text=True)
            if 'href="/support"' not in html:
                marker = '<a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="/admin/system-activity">'
                pos = html.find(marker)
                if pos >= 0:
                    link = ('<a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="/support">'
                            '<i data-feather="help-circle" class="me-2"></i>Support</a>')
                    html = html[:pos] + link + html[pos:]
                html = html.replace('<span class="text-muted small">Help (retired)</span>',
                                    '<a class="text-muted small text-decoration-none" href="/support">Support</a>')
                response.set_data(html)
                response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            pass
        return response

    app._bt38_support_nav_installed = True


_install_support_navigation()
