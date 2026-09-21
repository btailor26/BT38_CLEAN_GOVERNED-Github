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
