"""Single governed source of truth for BT38's production eBay OAuth scopes."""

from __future__ import annotations

import os


EBAY_COMMERCE_SHIPPING_SCOPE = (
    "https://api.ebay.com/oauth/api_scope/commerce.shipping"
)
EBAY_FINANCES_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.finances"
EBAY_RETURN_READ_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.return.read"
EBAY_RETURN_WRITE_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.return"
EBAY_LOGISTICS_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.logistics"

LEGACY_EBAY_OAUTH_SCOPES = (
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/commerce.notification.subscription",
    "https://api.ebay.com/oauth/api_scope/commerce.notification.subscription.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.listing.read",
)

DEFAULT_EBAY_OAUTH_SCOPES = (
    *LEGACY_EBAY_OAUTH_SCOPES,
    EBAY_COMMERCE_SHIPPING_SCOPE,
    EBAY_FINANCES_SCOPE,
    EBAY_RETURN_READ_SCOPE,
    EBAY_RETURN_WRITE_SCOPE,
    EBAY_LOGISTICS_SCOPE,
)


def governed_ebay_oauth_scopes() -> str:
    """Return the operator override plus BT38's complete governed scope set."""

    configured = (os.getenv("EBAY_SCOPES") or "").split()
    # eBay Developer Support requires the generic application scope to be
    # excluded from Authorization Code/User consent. It remains valid for
    # Client Credentials, which is a separate grant flow.
    generic_application_scope = "https://api.ebay.com/oauth/api_scope"
    configured = [scope for scope in configured if scope != generic_application_scope]
    aligned = list(dict.fromkeys([*configured, *DEFAULT_EBAY_OAUTH_SCOPES]))
    return " ".join(aligned)


def governed_ebay_refresh_scopes(credentials: dict | None = None) -> str | None:
    """Return a safe optional scope parameter for an eBay refresh request.

    eBay allows the scope parameter to be omitted; in that case the refreshed
    access token inherits the scopes from the seller's original consent grant.
    BT38 historically persisted ``oauth_granted_scope`` from the requested
    scope list when eBay's token response omitted ``scope``. When those two
    stored values are identical they therefore cannot prove the actual grant.
    Omitting ``scope`` is the only non-speculative way to preserve exactly what
    the refresh token was consented for and avoids falsely forcing a scope that
    the token may not contain.

    A distinct persisted granted value remains safe to request explicitly so
    older/legacy tokens continue to refresh only their known grant.
    """

    credentials = credentials or {}
    granted = str(credentials.get("oauth_granted_scope") or "").strip()
    requested = str(credentials.get("oauth_requested_scope") or "").strip()

    if granted and requested:
        granted_set = set(granted.split())
        requested_set = set(requested.split())
        if granted_set == requested_set:
            return None

    if granted:
        return granted

    # With no durable proof of the granted set, omit scope and let eBay bind the
    # new access token to the refresh token's real seller-consent grant.
    return None


def governed_ebay_access_token(store, *, force_refresh=False, source="governed_ebay_runtime"):
    """Return one valid seller access token; this is the only refresh authority."""
    import json
    from datetime import datetime, timedelta
    import requests
    from extensions import db

    raw = getattr(store, "api_key", None) or {}
    if isinstance(raw, str):
        try:
            credentials = json.loads(raw or "{}")
        except Exception:
            credentials = {}
    elif isinstance(raw, dict):
        credentials = dict(raw)
    else:
        credentials = {}

    token = str(credentials.get("access_token") or "").strip()
    expires_soon = True
    expires_at = credentials.get("access_token_expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is not None:
                expiry = expiry.replace(tzinfo=None)
            expires_soon = expiry <= datetime.utcnow() + timedelta(minutes=10)
        except Exception:
            expires_soon = True

    if token and not force_refresh and not expires_soon:
        return token

    refresh_token = str(credentials.get("refresh_token") or "").strip()
    client_id = str(os.getenv("EBAY_CLIENT_ID") or credentials.get("app_id") or credentials.get("client_id") or "").strip()
    client_secret = str(os.getenv("EBAY_CLIENT_SECRET") or credentials.get("cert_id") or credentials.get("client_secret") or "").strip()
    if not refresh_token or not client_id or not client_secret:
        raise RuntimeError("missing_ebay_refresh_credentials")

    scope = governed_ebay_refresh_scopes(credentials)
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if scope:
        data["scope"] = scope

    response = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        timeout=30,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}

    if response.status_code >= 300 or not payload.get("access_token"):
        raise RuntimeError(f"ebay_access_token_refresh_failed:{response.status_code}")

    now = datetime.utcnow()
    credentials.update({
        "access_token": payload.get("access_token"),
        "token_type": payload.get("token_type"),
        "access_token_expires_at": (
            now + timedelta(seconds=int(payload.get("expires_in", 7200)))
        ).isoformat(),
        "oauth_source": source,
        "oauth_requested_scope": scope or credentials.get("oauth_requested_scope"),
        "oauth_granted_scope": payload.get("scope") or credentials.get("oauth_granted_scope"),
        "refreshed_at": now.isoformat(),
        "sandbox": False,
    })
    store.api_key = json.dumps(credentials)
    store.is_active = True
    store.store_mode = "live"
    db.session.add(store)
    db.session.commit()
    return str(payload["access_token"])
