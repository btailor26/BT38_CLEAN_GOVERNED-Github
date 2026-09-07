"""Governed merchant-owned Royal Mail Click & Drop routes.

Connection and recovery are explicit user actions. There is no background poll,
second order importer, parallel shipment model or marketplace write path.
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from extensions import db
from royal_mail_models import RoyalMailConnection
from services.governed_royal_mail_label_readback import hydrate_royal_mail_label_for_order
from services.royal_mail_click_drop import (
    RoyalMailAPIError,
    RoyalMailClickDropClient,
    RoyalMailConfigurationError,
    decrypt_api_key,
    encrypt_api_key,
)


governed_royal_mail_bp = Blueprint("governed_royal_mail", __name__)


def ensure_royal_mail_connection_schema() -> None:
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
            "connection": {"connected": False, "status": "not_connected", "account_email": None, "validated_at": None, "last_error": None},
            "authentication": "click_drop_api_key",
        })
    return jsonify({"success": True, "connection": row.to_public_dict(), "authentication": "click_drop_api_key"})


@governed_royal_mail_bp.post("/governed/royal-mail/connection")
@login_required
def royal_mail_connect():
    body = request.get_json(silent=True) or {}
    account_email = str(body.get("account_email") or "").strip()[:255] or None
    api_key = str(body.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"success": False, "message": "Royal Mail Click & Drop API auth key is required."}), 400
    if body.get("password"):
        return jsonify({"success": False, "message": "Do not enter your Royal Mail website password. Click & Drop API connections use the account-specific API auth key."}), 400
    try:
        validation = RoyalMailClickDropClient(api_key=api_key).validate_connection()
        ciphertext = encrypt_api_key(api_key)
    except RoyalMailConfigurationError as exc:
        return jsonify({"success": False, "message": str(exc)}), 503
    except RoyalMailAPIError as exc:
        return jsonify({"success": False, "message": str(exc), "royal_mail_status_code": exc.status_code}), 400 if exc.status_code == 401 else 502

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
    return jsonify({"success": True, "connection": row.to_public_dict(), "validation": validation, "authentication": "click_drop_api_key"})


@governed_royal_mail_bp.post("/governed/royal-mail/connection/test")
@login_required
def royal_mail_test_connection():
    row = _connection()
    if row is None:
        return jsonify({"success": False, "message": "Royal Mail is not connected."}), 404
    try:
        validation = RoyalMailClickDropClient(api_key=decrypt_api_key(row.api_key_ciphertext)).validate_connection()
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
    row = _connection()
    if row is None or row.status != "connected":
        return jsonify({"success": False, "message": "Royal Mail is not connected."}), 409
    try:
        evidence = RoyalMailClickDropClient(api_key=decrypt_api_key(row.api_key_ciphertext)).get_exact_order_evidence(order_reference)
    except (RoyalMailConfigurationError, RoyalMailAPIError, ValueError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 502
    return jsonify({
        "success": True, "exact_order_only": True, "order_reference": order_reference,
        "orders": evidence.get("orders") or [], "details": evidence.get("details") or [],
        "details_available": bool(evidence.get("details_available")),
        "marketplace_write_started": False, "label_purchase_started": False, "broad_scan_started": False,
    })


@governed_royal_mail_bp.post("/governed/royal-mail/exact-label-recovery")
@login_required
def royal_mail_exact_label_recovery():
    """Persist one proven Click & Drop label into the existing FBMShipment authority."""
    body = request.get_json(silent=True) or {}
    try:
        store_id = int(body.get("store_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "store_id is required."}), 400
    order_id = str(body.get("marketplace_order_id") or "").strip()
    if not order_id:
        return jsonify({"success": False, "message": "marketplace_order_id is required."}), 400
    row = _connection()
    if row is None or row.status != "connected":
        return jsonify({"success": False, "message": "Royal Mail is not connected."}), 409
    try:
        result = hydrate_royal_mail_label_for_order(
            store_id=store_id,
            marketplace_order_id=order_id,
            api_key=decrypt_api_key(row.api_key_ciphertext),
        )
    except (RoyalMailConfigurationError, RoyalMailAPIError, ValueError) as exc:
        db.session.rollback()
        return jsonify({"success": False, "message": str(exc), "marketplace_write_started": False}), 502
    return jsonify(result), 200 if result.get("success") else 404
