"""Governed marketplace disconnect authority for persisted eBay OAuth grants."""

import base64
import json
import os

import requests


def revoke_persisted_ebay_grant(store):
    """Revoke the persisted eBay user grant before BT38 forgets the Store."""
    credentials = {}
    if isinstance(store.api_key, str):
        try:
            credentials = json.loads(store.api_key or "{}")
        except Exception:
            credentials = {}
    elif isinstance(store.api_key, dict):
        credentials = dict(store.api_key)

    refresh_token = str(credentials.get("refresh_token") or "").strip()
    access_token = str(credentials.get("access_token") or "").strip()
    token = refresh_token or access_token
    token_type_hint = "refresh_token" if refresh_token else "access_token"

    if not token:
        return {
            "ok": True,
            "revoked": False,
            "marketplace_action": False,
            "reason": "no_persisted_ebay_token",
        }

    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return {
            "ok": False,
            "revoked": False,
            "marketplace_action": False,
            "error": "missing_ebay_oauth_env",
        }

    basic = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")
    response = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token/revoke",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "token": token,
            "token_type_hint": token_type_hint,
        },
        timeout=30,
    )

    if response.status_code >= 300:
        return {
            "ok": False,
            "revoked": False,
            "marketplace_action": True,
            "error": "ebay_oauth_revocation_failed",
            "status_code": response.status_code,
        }

    return {
        "ok": True,
        "revoked": True,
        "marketplace_action": True,
        "token_type": token_type_hint,
    }
