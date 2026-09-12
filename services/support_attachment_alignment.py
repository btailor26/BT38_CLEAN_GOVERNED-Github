"""Private support-case evidence attachments.

Attachments stay inside the existing SupportCase authority. Evidence is stored in
Postgres rather than Fly's ephemeral filesystem, is never placed under /static,
and can only be downloaded after the same case-scope check used by the support
workflow. This module has no marketplace, carrier or payment-provider path.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import BytesIO

from flask import abort, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import app
from extensions import db
from services.support_case_alignment import SupportCase, _case_or_404, _is_admin


MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 3
MAX_ATTACHMENTS_PER_CASE = 25

_ALLOWED = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
}


class SupportCaseAttachment(db.Model):
    __tablename__ = "support_case_attachments"

    id = db.Column(db.Integer, primary_key=True)
    case_pk = db.Column(
        db.Integer,
        db.ForeignKey("support_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id = db.Column(db.Integer, nullable=False, index=True)
    uploader_role = db.Column(db.String(20), nullable=False, default="customer")
    filename = db.Column(db.String(220), nullable=False)
    content_type = db.Column(db.String(80), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    sha256_hex = db.Column(db.String(64), nullable=False, index=True)
    payload = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


with app.app_context():
    db.create_all()


def _extension(filename: str) -> str:
    name = str(filename or "").strip().lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _verified_content_type(filename: str, payload: bytes) -> str | None:
    """Verify supported evidence by content signature, not browser MIME alone."""
    ext = _extension(filename)
    expected = _ALLOWED.get(ext)
    if expected is None or not payload:
        return None
    if ext == ".png":
        return expected if payload.startswith(b"\x89PNG\r\n\x1a\n") else None
    if ext in {".jpg", ".jpeg"}:
        return expected if payload.startswith(b"\xff\xd8\xff") else None
    if ext == ".webp":
        return expected if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP" else None
    if ext == ".pdf":
        return expected if payload.startswith(b"%PDF-") else None
    if ext in {".txt", ".csv"}:
        if b"\x00" in payload:
            return None
        try:
            payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
        return expected
    return None


def _attachment_rows(case_pk: int) -> list[dict]:
    rows = (
        db.session.query(
            SupportCaseAttachment.id,
            SupportCaseAttachment.filename,
            SupportCaseAttachment.content_type,
            SupportCaseAttachment.byte_size,
            SupportCaseAttachment.uploader_role,
            SupportCaseAttachment.created_at,
        )
        .filter(SupportCaseAttachment.case_pk == int(case_pk))
        .order_by(SupportCaseAttachment.created_at.asc(), SupportCaseAttachment.id.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "filename": row.filename,
            "content_type": row.content_type,
            "byte_size": int(row.byte_size or 0),
            "uploader_role": row.uploader_role,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _human_size(value: int) -> str:
    size = max(0, int(value or 0))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@app.context_processor
def bt38_support_attachment_context():
    return {
        "support_attachments": _attachment_rows,
        "support_attachment_size": _human_size,
        "support_attachment_types": "PNG, JPG, WEBP, PDF, TXT or CSV",
        "support_attachment_max_mb": 5,
    }


@app.post("/support/cases/<case_id>/attachments")
@login_required
def bt38_support_upload_attachments(case_id):
    case = _case_or_404(case_id)
    if case.status == "closed":
        flash("Closed support cases cannot receive new attachments.", "warning")
        return redirect(url_for("bt38_support_case_page", case_id=case.case_id))

    files = [item for item in request.files.getlist("attachments") if item and item.filename]
    if not files:
        flash("Choose at least one file to attach.", "danger")
        return redirect(url_for("bt38_support_case_page", case_id=case.case_id))
    if len(files) > MAX_FILES_PER_UPLOAD:
        flash(f"Attach no more than {MAX_FILES_PER_UPLOAD} files at a time.", "danger")
        return redirect(url_for("bt38_support_case_page", case_id=case.case_id))

    existing = SupportCaseAttachment.query.filter_by(case_pk=case.id).count()
    if existing + len(files) > MAX_ATTACHMENTS_PER_CASE:
        flash(f"A support case can hold up to {MAX_ATTACHMENTS_PER_CASE} attachments.", "danger")
        return redirect(url_for("bt38_support_case_page", case_id=case.case_id))

    prepared = []
    total = 0
    for item in files:
        original = str(item.filename or "").strip()
        safe_name = secure_filename(original)[:220]
        if not safe_name or _extension(safe_name) not in _ALLOWED:
            flash("Unsupported attachment type. Use PNG, JPG, WEBP, PDF, TXT or CSV.", "danger")
            return redirect(url_for("bt38_support_case_page", case_id=case.case_id))

        payload = item.stream.read(MAX_ATTACHMENT_BYTES + 1)
        if not payload:
            flash(f"{safe_name} is empty.", "danger")
            return redirect(url_for("bt38_support_case_page", case_id=case.case_id))
        if len(payload) > MAX_ATTACHMENT_BYTES:
            flash(f"{safe_name} is larger than 5 MB.", "danger")
            return redirect(url_for("bt38_support_case_page", case_id=case.case_id))
        total += len(payload)
        if total > MAX_UPLOAD_BYTES:
            flash("The combined attachment upload is larger than 10 MB.", "danger")
            return redirect(url_for("bt38_support_case_page", case_id=case.case_id))

        verified_type = _verified_content_type(safe_name, payload)
        if verified_type is None:
            flash(f"{safe_name} does not match its permitted file type.", "danger")
            return redirect(url_for("bt38_support_case_page", case_id=case.case_id))
        prepared.append((safe_name, verified_type, payload))

    role = "admin" if _is_admin() else "customer"
    for safe_name, content_type, payload in prepared:
        db.session.add(
            SupportCaseAttachment(
                case_pk=case.id,
                uploaded_by_user_id=int(current_user.id),
                uploader_role=role,
                filename=safe_name,
                content_type=content_type,
                byte_size=len(payload),
                sha256_hex=sha256(payload).hexdigest(),
                payload=payload,
            )
        )

    if not _is_admin() and case.status in {"resolved", "waiting_customer"}:
        case.status = "open"
    elif _is_admin() and case.status == "open":
        case.status = "in_progress"
    case.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"{len(prepared)} attachment{'s' if len(prepared) != 1 else ''} added securely.", "success")
    return redirect(url_for("bt38_support_case_page", case_id=case.case_id))


@app.get("/support/cases/<case_id>/attachments/<int:attachment_id>")
@login_required
def bt38_support_download_attachment(case_id, attachment_id):
    case = _case_or_404(case_id)
    attachment = SupportCaseAttachment.query.filter_by(
        id=int(attachment_id), case_pk=case.id
    ).first()
    if attachment is None:
        abort(404)

    response = send_file(
        BytesIO(bytes(attachment.payload)),
        mimetype=attachment.content_type,
        as_attachment=True,
        download_name=attachment.filename,
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
