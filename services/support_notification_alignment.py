"""Expose support case reply attention through the existing BT38 notification bell.

This wraps the already-registered governed notification read only. SupportCase and
SupportCaseMessage remain the sole support authority: no notification table,
worker, poller, email provider, marketplace read or business-data mutation is
introduced. Only safe case metadata is added; support message bodies and captured
case context never enter the bell payload.
"""
from __future__ import annotations

from functools import wraps

from flask import current_app, jsonify, request
from flask_login import current_user

from extensions import db
from services.account_profile_alignment import _account_for_user
from services.support_case_alignment import SupportCase, SupportCaseMessage

_ACTIVE_STATES = {"open", "in_progress", "waiting_customer"}


def _is_admin() -> bool:
    return bool(
        current_user
        and getattr(current_user, "is_authenticated", False)
        and str(getattr(current_user, "role", "")).strip().lower() == "admin"
    )


def _candidate_cases(limit: int = 100) -> list[SupportCase]:
    query = SupportCase.query
    if not _is_admin():
        account, _ = _account_for_user(current_user.id)
        if account is None:
            return []
        query = query.filter_by(account_id=account.id)
    return (
        query.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc())
        .limit(max(1, min(int(limit or 100), 250)))
        .all()
    )


def _latest_messages(cases: list[SupportCase]) -> dict[int, SupportCaseMessage]:
    case_ids = [int(case.id) for case in cases if getattr(case, "id", None) is not None]
    if not case_ids:
        return {}
    latest_ids = (
        db.session.query(
            SupportCaseMessage.case_pk.label("case_pk"),
            db.func.max(SupportCaseMessage.id).label("latest_id"),
        )
        .filter(SupportCaseMessage.case_pk.in_(case_ids))
        .group_by(SupportCaseMessage.case_pk)
        .subquery()
    )
    rows = (
        SupportCaseMessage.query
        .join(latest_ids, SupportCaseMessage.id == latest_ids.c.latest_id)
        .all()
    )
    return {int(row.case_pk): row for row in rows}


def _has_admin_reply(case_id: int) -> bool:
    return (
        SupportCaseMessage.query
        .filter_by(case_pk=int(case_id), author_role="admin")
        .with_entities(SupportCaseMessage.id)
        .first()
        is not None
    )


def _record(case: SupportCase, latest: SupportCaseMessage | None) -> tuple[dict | None, bool]:
    """Return safe bell metadata plus whether the recipient currently owes attention."""
    status = str(case.status or "open").strip().lower()
    priority = str(case.priority or "normal").strip().lower()
    case_id = str(case.case_id or f"Case {case.id}").strip()
    subject = str(case.subject or "Support case").strip()[:120]
    active = status in _ACTIVE_STATES

    if _is_admin():
        latest_role = str(getattr(latest, "author_role", "") or "").strip().lower()
        if latest is None and active and not _has_admin_reply(case.id):
            title = "New support case"
            attention = True
            changed_at = case.created_at or case.updated_at
            event_suffix = "opened"
        elif latest_role == "customer" and active:
            title = "Customer replied"
            attention = True
            changed_at = latest.created_at or case.updated_at
            event_suffix = f"customer:{latest.id}"
        else:
            return None, False
    else:
        latest_role = str(getattr(latest, "author_role", "") or "").strip().lower()
        if latest_role != "admin":
            return None, False
        title = "BT38 Support replied"
        attention = active
        changed_at = latest.created_at or case.updated_at
        event_suffix = f"admin:{latest.id}"

    record = {
        "event_key": f"support:{case.id}:{event_suffix}",
        "id": f"support:{case.id}:{event_suffix}",
        "log_type": "support_attention" if attention else "support_update",
        "platform": "BT38 Support",
        "title": title,
        "case_id": case_id,
        "case_status": status,
        "priority": priority,
        "message": f"{case_id} · {subject}",
        "url": f"/support/cases/{case_id}",
        "created_at": changed_at.isoformat() if changed_at else None,
    }
    return record, attention


def support_notification_snapshot(limit: int = 100) -> dict:
    cases = _candidate_cases(limit=limit)
    latest = _latest_messages(cases)
    records = []
    attention_count = 0
    for case in cases:
        record, attention = _record(case, latest.get(int(case.id)))
        if record is None:
            continue
        records.append(record)
        if attention:
            attention_count += 1
    records.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return {
        "records": records[: max(1, min(int(limit or 100), 100))],
        "attention_count": attention_count,
    }


def _install() -> None:
    from app import app

    endpoint = "governed.governed_ui_notifications"
    original = app.view_functions.get(endpoint)
    if original is None:
        raise RuntimeError("governed notification endpoint is not registered")
    if getattr(original, "_bt38_support_notification_aligned", False):
        return

    @wraps(original)
    def support_aligned_notifications(*args, **kwargs):
        response = current_app.make_response(original(*args, **kwargs))
        if response.status_code != 200:
            return response
        payload = response.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return response

        try:
            requested_limit = int(request.args.get("limit") or 20)
        except Exception:
            requested_limit = 20
        requested_limit = max(1, min(requested_limit, 50))

        snapshot = support_notification_snapshot(limit=100)
        existing_records = list(payload.get("records") or [])
        combined = existing_records + list(snapshot["records"])
        combined.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        payload["records"] = combined[:requested_limit]
        payload["support_attention_count"] = int(snapshot["attention_count"])
        payload["latest_event_at"] = (
            payload["records"][0].get("created_at") if payload["records"] else None
        )
        return jsonify(payload)

    support_aligned_notifications._bt38_support_notification_aligned = True
    app.view_functions[endpoint] = support_aligned_notifications
    app.logger.info(
        "BT38 support notifications aligned to existing governed bell; "
        "case metadata only, no second notification authority"
    )


_install()
