"""COFI controls on the existing BT38 owner fuse board.

This module does not create a second settings system or COFI execution path.
It stores COFI permission switches in the existing SystemConfig authority and
exposes one compact owner/admin API for the existing /settings cockpit.
Future COFI features should read ``cofi_control_state()`` before surfacing or
running COFI work.
"""
from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required

from app import app
from extensions import db
from models import SystemConfig


COFI_CONFIG_KEYS = (
    "cofi_enabled",
    "cofi_opportunities_enabled",
    "cofi_customer_visibility_enabled",
)


def _is_on(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _admin_allowed() -> bool:
    try:
        return bool(
            current_user
            and current_user.is_authenticated
            and str(getattr(current_user, "role", "")).strip().lower() == "admin"
        )
    except Exception:
        return False


def cofi_control_state() -> dict:
    """Return the persisted COFI fuse state from the existing SystemConfig table."""
    rows = SystemConfig.query.filter(SystemConfig.key.in_(COFI_CONFIG_KEYS)).all()
    raw = {key: False for key in COFI_CONFIG_KEYS}
    for row in rows:
        raw[row.key] = _is_on(row.value)

    return {
        **raw,
        "effective_opportunities": bool(
            raw["cofi_enabled"] and raw["cofi_opportunities_enabled"]
        ),
        "effective_customer_visibility": bool(
            raw["cofi_enabled"]
            and raw["cofi_opportunities_enabled"]
            and raw["cofi_customer_visibility_enabled"]
        ),
    }


def _set_config(key: str, value: bool) -> None:
    row = SystemConfig.query.filter_by(key=key).first()
    stored = "true" if bool(value) else "false"
    if row is None:
        row = SystemConfig(key=key, value=stored)
        db.session.add(row)
    else:
        row.value = stored


@app.get("/governed/settings/cofi")
@login_required
def bt38_cofi_settings_state():
    if not _admin_allowed():
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "admin_required",
        }), 403

    return jsonify({
        "ok": True,
        "success": True,
        "governed": True,
        "authority": "SystemConfig",
        "controls": cofi_control_state(),
    }), 200


@app.post("/governed/settings/cofi")
@login_required
def bt38_cofi_settings_update():
    if not _admin_allowed():
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "admin_required",
        }), 403

    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key") or "").strip()
    if key not in COFI_CONFIG_KEYS:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "unsupported_cofi_setting",
        }), 400

    value = payload.get("value")
    if isinstance(value, bool):
        enabled = value
    elif str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}:
        enabled = True
    elif str(value).strip().lower() in {"0", "false", "no", "off", "disabled"}:
        enabled = False
    else:
        return jsonify({
            "ok": False,
            "success": False,
            "governed": True,
            "error": "invalid_boolean_value",
        }), 400

    _set_config(key, enabled)
    db.session.commit()

    return jsonify({
        "ok": True,
        "success": True,
        "governed": True,
        "authority": "SystemConfig",
        "updated": key,
        "controls": cofi_control_state(),
    }), 200
