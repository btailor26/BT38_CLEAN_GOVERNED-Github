"""BT38 account-scoped support case workflow.

The public /support page remains untouched. Authenticated case handling lives at
/support/cases and /admin/support/cases. This module never calls marketplaces,
payment providers or carriers and never mutates inventory/order truth.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from flask import abort, flash, redirect, render_template, request, url_for, jsonify, Response
from flask_login import current_user, login_required

from app import app
from extensions import db
from services.account_profile_alignment import _account_for_user
from models import MarketplaceOrder


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
# Only non-secret operational identifiers may cross from a BT38 page into a case.
_CONTEXT_KEYS = {
    "marketplace", "store", "store_id", "order_id", "amazon_order_id", "ebay_order_id",
    "shipment_id", "tracking", "tracking_number", "sku", "listing_id", "item_id",
    "warehouse_stock_id", "group_id", "invoice_id", "assignment_id", "review_event_id",
    "integration", "carrier", "connection", "entity_type", "entity_id",
}
_CONTEXT_BLOCKED_FRAGMENTS = (
    "token", "secret", "password", "credential", "authorization", "api_key", "apikey",
    "private_key", "public_key", "card", "cookie", "session", "signature",
)


class SupportCase(db.Model):
    __tablename__ = "support_cases"
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.String(40), unique=True, nullable=True, index=True)
    # Public access applications enter the existing support queue before a
    # CustomerAccount exists. Normal authenticated support cases remain
    # account-scoped; only the access-application alignment may be unscoped.
    account_id = db.Column(db.Integer, db.ForeignKey("customer_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    opened_by_user_id = db.Column(db.Integer, nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False, index=True)
    subject = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="normal", index=True)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    affected_area = db.Column(db.String(160))
    source_page = db.Column(db.String(500))
    context_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class SupportCaseMessage(db.Model):
    __tablename__ = "support_case_messages"
    id = db.Column(db.Integer, primary_key=True)
    case_pk = db.Column(db.Integer, db.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = db.Column(db.Integer, nullable=True, index=True)
    author_role = db.Column(db.String(20), nullable=False, default="customer")
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class SupportCaseAttachment(db.Model):
    """File evidence attached to the existing support-case authority."""
    __tablename__ = "support_case_attachments"
    id = db.Column(db.Integer, primary_key=True)
    case_pk = db.Column(db.Integer, db.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id = db.Column(db.Integer, nullable=False, index=True)
    uploader_role = db.Column(db.String(20), nullable=False, default="customer")
    filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(255), nullable=False, default="application/octet-stream")
    byte_size = db.Column(db.Integer, nullable=False, default=0)
    sha256_hex = db.Column(db.String(64), nullable=False)
    payload = db.Column(db.LargeBinary, nullable=False)
    # Newer aliases are retained for compatibility with the current support UI.
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    content = db.Column(db.LargeBinary, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


def _align_support_attachment_schema() -> None:
    """Safely align an older existing attachment table before uploads use it."""
    from sqlalchemy import text
    statements = (
        "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS uploaded_by_user_id INTEGER",
        "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS filename VARCHAR(255)",
        "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS content_type VARCHAR(255)",
        "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS size_bytes INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS content BYTEA",
        "ALTER TABLE support_case_attachments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    )
    for statement in statements:
        db.session.execute(text(statement))
    db.session.commit()


with app.app_context():
    db.create_all()
    _align_support_attachment_schema()


def _is_admin() -> bool:
    return str(getattr(current_user, "role", "") or "").strip().lower() == "admin"


def _clean(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _customer_scope():
    return _account_for_user(current_user.id)


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
        "open": "Open", "in_progress": "In progress", "waiting_customer": "Waiting for customer",
        "resolved": "Resolved", "closed": "Closed",
    }.get(value, str(value or "").replace("_", " ").title())


def _safe_source_page(value) -> str:
    """Keep only a local BT38 path plus allowlisted, non-secret query identifiers."""
    raw = _clean(value, 1200)
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    path = parts.path if parts.path.startswith("/") else ""
    if not path or path.startswith("//"):
        return ""
    safe_query = []
    for key, val in parse_qsl(parts.query, keep_blank_values=False):
        normal = str(key or "").strip().lower()
        if normal in _CONTEXT_KEYS and not any(fragment in normal for fragment in _CONTEXT_BLOCKED_FRAGMENTS):
            safe_query.append((normal, _clean(val, 180)))
    return (path + (("?" + urlencode(safe_query)) if safe_query else ""))[:500]


def _context_from_source(source_page: str) -> dict:
    """Snapshot only identifiers already present in the originating BT38 URL."""
    if not source_page:
        return {}
    parts = urlsplit(source_page)
    context = {"source_page": parts.path[:240]}
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        normal = str(key or "").strip().lower()
        if normal in _CONTEXT_KEYS and not any(fragment in normal for fragment in _CONTEXT_BLOCKED_FRAGMENTS):
            context[normal] = _clean(value, 180)
    return context


def _case_context(case: SupportCase) -> dict:
    try:
        value = json.loads(case.context_json or "{}")
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


@app.context_processor
def bt38_support_context():
    return {
        "support_categories": SUPPORT_CATEGORIES,
        "support_category_labels": _CATEGORY_MAP,
        "support_status_label": _status_label,
    }


@app.get("/support/cases")
@login_required
def bt38_support_cases_page():
    account, _ = _customer_scope()
    if account is None:
        flash("Your BT38 customer account is not available yet.", "warning")
        return redirect(url_for("bt38_profile_page"))
    cases = (SupportCase.query.filter_by(account_id=account.id)
             .order_by(SupportCase.updated_at.desc(), SupportCase.id.desc()).limit(250).all())
    source_page = _safe_source_page(request.args.get("from"))
    source_context = _context_from_source(source_page)
    return render_template("support_cases.html", cases=cases, account=account, admin_view=False,
                           source_page=source_page, source_context=source_context)


@app.post("/support/cases/new")
@login_required
def bt38_support_create_case():
    account, _ = _customer_scope()
    if account is None:
        flash("A customer account is required to open a support case.", "danger")
        return redirect(url_for("bt38_support_cases_page"))
    category = _clean(request.form.get("category"), 50).lower()
    subject = _clean(request.form.get("subject"), 180)
    description = _clean(request.form.get("description"), 8000)
    priority = _clean(request.form.get("priority"), 20).lower() or "normal"
    affected_area = _clean(request.form.get("affected_area"), 160)
    source_page = _safe_source_page(request.form.get("source_page"))
    context = _context_from_source(source_page)
    if category not in _CATEGORY_MAP:
        flash("Choose a valid support category.", "danger")
        return redirect(url_for("bt38_support_cases_page"))
    if priority not in _VALID_PRIORITY:
        priority = "normal"
    if not subject or not description:
        flash("Add a subject and describe what is happening.", "danger")
        return redirect(url_for("bt38_support_cases_page"))
    case = SupportCase(
        account_id=account.id, opened_by_user_id=int(current_user.id), category=category,
        subject=subject, description=description, priority=priority, status="open",
        affected_area=affected_area or None, source_page=source_page or None,
        context_json=json.dumps(context, ensure_ascii=False, sort_keys=True) if context else None,
    )
    db.session.add(case)
    db.session.flush()
    case.case_id = _case_number(case)
    db.session.commit()
    flash(f"Support case {case.case_id} has been opened.", "success")
    return redirect(url_for("bt38_support_case_page", case_id=case.case_id))


@app.post("/support/cases/manual-upload-review")
@login_required
def bt38_support_manual_upload_review():
    """DB-first manual evidence review; support is only the unresolved fallback."""
    account, _ = _customer_scope()
    if account is None:
        return jsonify({"ok": False, "error": "customer_account_required"}), 400
    files = [item for item in request.files.getlist("files") if item and item.filename]
    if not files:
        return jsonify({"ok": False, "error": "no_files"}), 400

    # Read each upload once. Before a support case can exist, ask persisted order
    # truth whether the evidence names an order BT38 already knows. This is a
    # DB-only review: no marketplace/provider call and no operational mutation.
    evidence = []
    candidate_order_ids = set()
    names = []
    for item in files:
        name = _clean(item.filename, 255)
        payload = item.read()
        names.append(name)
        evidence.append((name, _clean(item.mimetype, 255) or None, payload))
        sample = payload[:2_000_000].decode("utf-8", errors="ignore")
        for token in re.findall(r"(?<![A-Za-z0-9])(?:\\d{3}-\\d{7}-\\d{7}|\\d{2}-\\d{5}-\\d{5})(?![A-Za-z0-9])", sample):
            candidate_order_ids.add(token)

    matched_orders = []
    if candidate_order_ids:
        rows = (
            MarketplaceOrder.query
            .filter(MarketplaceOrder.marketplace_order_id.in_(sorted(candidate_order_ids)))
            .all()
        )
        matched_orders = sorted({
            str(row.marketplace_order_id)
            for row in rows
            if getattr(row, "marketplace_order_id", None)
        })

    db_review = {
        "completed": True,
        "authority": "marketplace_orders",
        "candidate_order_ids": sorted(candidate_order_ids),
        "matched_order_ids": matched_orders,
    }

    # An order match does not prove what an unknown file column/format means.
    # No approved FBM manual-file format mapping exists yet, so unresolved
    # evidence falls through to the existing support authority only after the
    # persisted DB review above. Never guess fields into shipment/order truth.
    case = SupportCase(
        account_id=account.id,
        opened_by_user_id=int(current_user.id),
        category="data_review",
        subject="Manual Upload — Pending / Under Review",
        description=(
            "BT38 checked persisted DB truth first. "
            + (f"Matched order(s): {', '.join(matched_orders)}. " if matched_orders else "No exact persisted order match was found. ")
            + "The uploaded source/format is not yet an approved FBM manual-file mapping, so Admin mapping is required before any operational truth may be updated.\n\nFiles: "
            + ", ".join(names)
        ),
        priority="normal",
        status="open",
        affected_area="FBM Manual Upload",
        source_page="/fbm",
        context_json=json.dumps({
            "source_page": "/fbm",
            "manual_upload": True,
            "review_state": "under_review",
            "filenames": names,
            "db_review": db_review,
        }, ensure_ascii=False, sort_keys=True),
    )
    db.session.add(case)
    db.session.flush()
    case.case_id = _case_number(case)

    for name, content_type, payload in evidence:
        evidence_type = content_type or "application/octet-stream"
        evidence_size = len(payload)
        db.session.add(SupportCaseAttachment(
            case_pk=case.id,
            uploaded_by_user_id=int(current_user.id),
            uploader_role="admin" if _is_admin() else "customer",
            filename=name,
            content_type=evidence_type,
            byte_size=evidence_size,
            sha256_hex=hashlib.sha256(payload).hexdigest(),
            payload=payload,
            size_bytes=evidence_size,
            content=payload,
        ))
    db.session.commit()
    return jsonify({
        "ok": True,
        "review_state": "under_review",
        "case_id": case.case_id,
        "case_url": url_for("bt38_support_case_page", case_id=case.case_id),
        "db_review": db_review,
    })


@app.get("/admin/support/cases/<case_id>/attachments/<int:attachment_id>")
@login_required
def bt38_admin_support_case_attachment(case_id, attachment_id):
    if not _is_admin():
        abort(403)
    case = _case_or_404(case_id)
    attachment = SupportCaseAttachment.query.filter_by(id=attachment_id, case_pk=case.id).first()
    if attachment is None:
        abort(404)
    evidence_payload = attachment.content if attachment.content is not None else attachment.payload
    response = Response(evidence_payload, mimetype=attachment.content_type or "application/octet-stream")
    response.headers["Content-Disposition"] = 'attachment; filename="' + attachment.filename.replace('"', "") + '"'
    return response


@app.route("/support/cases/<case_id>", methods=["GET", "POST"])
@login_required
def bt38_support_case_page(case_id):
    case = _case_or_404(case_id)
    if request.method == "POST":
        body = _clean(request.form.get("message"), 8000)
        if not body:
            flash("Enter a message before sending.", "danger")
            return redirect(url_for("bt38_support_case_page", case_id=case.case_id))
        db.session.add(SupportCaseMessage(case_pk=case.id, author_user_id=int(current_user.id),
                                          author_role="admin" if _is_admin() else "customer", body=body))
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
    attachments = (SupportCaseAttachment.query.filter_by(case_pk=case.id)
                   .order_by(SupportCaseAttachment.created_at.asc(), SupportCaseAttachment.id.asc()).all())
    return render_template("support_case.html", case=case, messages=messages, attachments=attachments,
                           case_context=_case_context(case), is_support_admin=_is_admin())


@app.get("/admin/support/cases")
@login_required
def bt38_admin_support_cases_page():
    if not _is_admin():
        abort(403)
    status = _clean(request.args.get("status"), 30).lower()
    query = SupportCase.query
    if status in _VALID_STATUS:
        query = query.filter_by(status=status)
    cases = query.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc()).limit(500).all()
    counts = {state: SupportCase.query.filter_by(status=state).count() for state in _VALID_STATUS}
    return render_template("support_cases.html", cases=cases, account=None, admin_view=True,
                           support_counts=counts, selected_status=status, source_page="", source_context={})


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


@app.post("/admin/support/cases/<case_id>/access-decision")
@login_required
def bt38_admin_support_access_decision(case_id):
    """Align a pre-account support case with the existing application authority."""
    if not _is_admin():
        abort(403)
    case = _case_or_404(case_id)
    context = _case_context(case)
    application_id = context.get("application_id")
    if case.account_id is not None or not application_id:
        abort(404)
    decision = _clean(request.form.get("decision"), 20).lower()
    if decision not in {"approved", "rejected", "pending"}:
        abort(400)
    return redirect(url_for(
        "bt38_early_access_application_decision",
        application_id=int(application_id),
        decision=decision,
        support_case=case.case_id,
    ), code=307)


def _support_origin_url() -> str:
    """Build a local, sanitized origin URL from the page currently being rendered."""
    if request.path.startswith("/support") or request.path.startswith("/static"):
        return ""
    pairs = []
    for key in request.args:
        normal = str(key or "").strip().lower()
        if normal not in _CONTEXT_KEYS or any(fragment in normal for fragment in _CONTEXT_BLOCKED_FRAGMENTS):
            continue
        for value in request.args.getlist(key):
            pairs.append((normal, _clean(value, 180)))
    origin = request.path + (("?" + urlencode(pairs)) if pairs else "")
    return _safe_source_page(origin)


def _install_support_navigation() -> None:
    if getattr(app, "_bt38_support_nav_installed", False):
        return

    @app.after_request
    def bt38_support_navigation(response):
        try:
            if response.status_code != 200 or "text/html" not in str(response.content_type or "").lower():
                return response
            html = response.get_data(as_text=True)
            if 'href="/support/cases"' not in html:
                marker = '<a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="/admin/system-activity">'
                pos = html.find(marker)
                if pos >= 0:
                    origin = _support_origin_url()
                    href = "/support/cases" + (("?from=" + quote(origin, safe="")) if origin else "")
                    link = ('<a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="' + href + '">'
                            '<i data-feather="help-circle" class="me-2"></i>Support</a>')
                    html = html[:pos] + link + html[pos:]
                    response.set_data(html)
                    response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            pass
        return response

    app._bt38_support_nav_installed = True


_install_support_navigation()
