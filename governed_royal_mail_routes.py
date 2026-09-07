"""Governed merchant-owned Royal Mail Click & Drop connection routes.

Connection validation is an explicit user action. No background polling, order
creation, label purchase or marketplace write is introduced here.
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from extensions import db
from royal_mail_models import RoyalMailConnection
from services.royal_mail_click_drop import (
    RoyalMailAPIError,
    RoyalMailClickDropClient,
    RoyalMailConfigurationError,
    decrypt_api_key,
    encrypt_api_key,
)


governed_royal_mail_bp = Blueprint("governed_royal_mail", __name__)


def ensure_royal_mail_connection_schema() -> None:
    """Create only the provider-connection table if it does not yet exist."""
    RoyalMailConnection.__table__.create(bind=db.engine, checkfirst=True)


def _connection() -> RoyalMailConnection | None:
    return RoyalMailConnection.query.filter_by(user_id=current_user.id).first()


@governed_royal_mail_bp.get("/governed/royal-mail/connection")
@login_required
def royal_mail_connection_status():
    row = _connection()
    if row is None:
        return jsonify({
            "success": True,
            "connection": {
                "connected": False,
                "status": "not_connected",
                "account_email": None,
                "validated_at": None,
                "last_error": None,
            },
            "authentication": "click_drop_api_key",
        })
    return jsonify({
        "success": True,
        "connection": row.to_public_dict(),
        "authentication": "click_drop_api_key",
    })


@governed_royal_mail_bp.post("/governed/royal-mail/connection")
@login_required
def royal_mail_connect():
    body = request.get_json(silent=True) or {}
    account_email = str(body.get("account_email") or "").strip()[:255] or None
    api_key = str(body.get("api_key") or "").strip()
    if not api_key:
        return jsonify({
            "success": False,
            "message": "Royal Mail Click & Drop API auth key is required.",
        }), 400

    # Royal Mail's public Click & Drop API does not authenticate with the user's
    # normal website password. Deliberately refuse to collect/store one.
    if body.get("password"):
        return jsonify({
            "success": False,
            "message": "Do not enter your Royal Mail website password. Click & Drop API connections use the account-specific API auth key.",
        }), 400

    try:
        client = RoyalMailClickDropClient(api_key=api_key)
        validation = client.validate_connection()
        ciphertext = encrypt_api_key(api_key)
    except RoyalMailConfigurationError as exc:
        return jsonify({"success": False, "message": str(exc)}), 503
    except RoyalMailAPIError as exc:
        return jsonify({
            "success": False,
            "message": str(exc),
            "royal_mail_status_code": exc.status_code,
        }), 400 if exc.status_code == 401 else 502

    row = _connection()
    if row is None:
        row = RoyalMailConnection(user_id=current_user.id, api_key_ciphertext=ciphertext)
        db.session.add(row)
    row.account_email = account_email
    row.api_key_ciphertext = ciphertext
    row.status = "connected"
    row.last_error = None
    row.validated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "success": True,
        "connection": row.to_public_dict(),
        "validation": validation,
        "authentication": "click_drop_api_key",
    })


@governed_royal_mail_bp.post("/governed/royal-mail/connection/test")
@login_required
def royal_mail_test_connection():
    row = _connection()
    if row is None:
        return jsonify({"success": False, "message": "Royal Mail is not connected."}), 404
    try:
        api_key = decrypt_api_key(row.api_key_ciphertext)
        validation = RoyalMailClickDropClient(api_key=api_key).validate_connection()
    except (RoyalMailConfigurationError, RoyalMailAPIError) as exc:
        row.status = "auth_error"
        row.last_error = str(exc)
        db.session.commit()
        return jsonify({"success": False, "message": str(exc)}), 502
    row.status = "connected"
    row.last_error = None
    row.validated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "connection": row.to_public_dict(), "validation": validation})


@governed_royal_mail_bp.get("/governed/royal-mail/orders/<path:order_reference>")
@login_required
def royal_mail_exact_order(order_reference: str):
    """Read one exact Click & Drop order/reference; never scan or mutate."""
    row = _connection()
    if row is None or row.status != "connected":
        return jsonify({"success": False, "message": "Royal Mail is not connected."}), 409
    try:
        api_key = decrypt_api_key(row.api_key_ciphertext)
        orders = RoyalMailClickDropClient(api_key=api_key).get_exact_orders(order_reference)
    except (RoyalMailConfigurationError, RoyalMailAPIError, ValueError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 502

    return jsonify({
        "success": True,
        "exact_order_only": True,
        "order_reference": order_reference,
        "orders": orders,
        "count": len(orders),
        "marketplace_write_started": False,
        "label_purchase_started": False,
        "broad_scan_started": False,
    })
