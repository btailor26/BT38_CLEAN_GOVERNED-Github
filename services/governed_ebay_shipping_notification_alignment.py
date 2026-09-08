"""Optional eBay shipment-tracking notification alignment.

ORDER_CONFIRMATION remains the required sale intake. ITEM_MARKED_SHIPPED is a
tracking accelerator: this module obtains a commerce.shipping-scoped seller
token and, when permitted, adds the subscription to BT38's existing webhook
destination. A legacy seller authorization without that grant remains usable;
bounded Fulfillment API readback stays the recovery authority.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import requests

from extensions import db
from services.governed_ebay_notification_registration import (
    NOTIFICATION_BASE_URL,
    _decode_store_credentials,
    _ensure_subscription,
    _get_topic_subscriptions,
    _headers,
    _safe_response_payload,
)
from services.governed_ebay_oauth_scopes import governed_ebay_refresh_scopes


SHIPPING_TOPIC_ID = "ITEM_MARKED_SHIPPED"
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"


def _persist_shipping_consent_state(
    store: Any,
    *,
    required: bool,
    enabled: bool,
    reason: str | None,
    subscription_id: str | None = None,
    destination_id: str | None = None,
    subscription_status: str | None = None,
    verified: bool = False,
) -> None:
    """Persist optional shipment consent and exact eBay readback evidence."""
    creds = _decode_store_credentials(store)
    now = datetime.utcnow().isoformat()
    if enabled:
        state = "ENABLED"
    elif required:
        state = "AUTHORIZATION_REQUIRED"
    else:
        state = "ERROR"
    creds.update(
        {
            "ebay_shipping_notification_status": state,
            "ebay_shipping_notification_reauthorization_required": bool(required),
            "ebay_shipping_notification_reason": str(reason or ""),
            "ebay_shipping_notification_attempted_at": now,
        }
    )
    if subscription_id is not None:
        creds["ebay_shipping_notification_subscription_id"] = str(subscription_id)
    if destination_id is not None:
        creds["ebay_shipping_notification_destination_id"] = str(destination_id)
    if subscription_status is not None:
        creds["ebay_shipping_notification_subscription_status"] = str(
            subscription_status
        ).upper()
    if verified:
        creds["ebay_shipping_notification_verified_at"] = now
    store.api_key = json.dumps(creds)
    db.session.commit()


def _shipping_access_token(store: Any) -> dict[str, Any]:
    creds = _decode_store_credentials(store)
    refresh_token = str(creds.get("refresh_token") or "").strip()
    client_id = str(os.getenv("EBAY_CLIENT_ID") or creds.get("client_id") or "").strip()
    client_secret = str(os.getenv("EBAY_CLIENT_SECRET") or creds.get("client_secret") or "").strip()
    if not refresh_token or not client_id or not client_secret:
        return {
            "ok": False,
            "authorization_required": False,
            "reason": "ebay_shipping_token_credentials_missing",
        }

    # Refresh from the exact seller grant already persisted by BT38. eBay's
    # ITEM_MARKED_SHIPPED path needs commerce.shipping in addition to the
    # standard/user-subscription scopes used by the Notification API. Asking
    # for commerce.shipping alone drops those companion scopes and can make an
    # otherwise valid newly reauthorized grant fail at token mint/subscription.
    refresh_scopes = governed_ebay_refresh_scopes(creds)
    response = requests.post(
        EBAY_TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": refresh_scopes,
        },
        timeout=30,
    )
    if response.status_code in {400, 401, 403}:
        return {
            "ok": False,
            "authorization_required": True,
            "reason": "commerce_shipping_scope_not_granted",
            "status_code": response.status_code,
            "error": response.text[:500],
        }
    if response.status_code >= 400:
        return {
            "ok": False,
            "authorization_required": False,
            "reason": "ebay_shipping_token_failed",
            "status_code": response.status_code,
            "error": response.text[:500],
        }

    token = str((response.json() or {}).get("access_token") or "").strip()
    if not token:
        return {
            "ok": False,
            "authorization_required": False,
            "reason": "ebay_shipping_token_missing_access_token",
        }
    return {"ok": True, "access_token": token}


def _topic_probe(*, access_token: str) -> dict[str, Any]:
    response = requests.get(
        f"{NOTIFICATION_BASE_URL}/topic/{SHIPPING_TOPIC_ID}",
        headers=_headers(access_token),
        timeout=30,
    )
    if response.status_code in {401, 403}:
        return {
            "ok": False,
            "authorization_required": True,
            "status_code": response.status_code,
            "schema_version": "",
        }
    if response.status_code != 200:
        return {
            "ok": False,
            "authorization_required": False,
            "status_code": response.status_code,
            "schema_version": "",
        }

    payload = _safe_response_payload(response)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "authorization_required": False,
            "status_code": response.status_code,
            "schema_version": "",
        }

    supported = payload.get("supportedPayloads") or []
    for row in supported:
        if not isinstance(row, dict):
            continue
        formats = row.get("format") or []
        if isinstance(formats, str):
            formats = [formats]
        if "JSON" not in {str(value).upper() for value in formats}:
            continue
        version = str(row.get("schemaVersion") or "").strip()
        if version:
            return {
                "ok": True,
                "authorization_required": False,
                "status_code": response.status_code,
                "schema_version": version,
            }

    return {
        "ok": False,
        "authorization_required": False,
        "status_code": response.status_code,
        "schema_version": "",
    }


def _shipping_subscription_readback(
    *,
    access_token: str,
    destination_id: str,
    subscription_id: str,
) -> dict[str, Any]:
    """Read eBay back and prove the exact shipped subscription is enabled."""
    subscriptions = _get_topic_subscriptions(
        access_token=access_token,
        topic_id=SHIPPING_TOPIC_ID,
    )
    for row in subscriptions:
        if not isinstance(row, dict):
            continue
        if str(row.get("subscriptionId") or "") != str(subscription_id):
            continue
        actual_topic = str(row.get("topicId") or "")
        actual_destination = str(row.get("destinationId") or "")
        status = str(row.get("status") or "").upper()
        exact_topic = actual_topic == SHIPPING_TOPIC_ID
        exact_destination = actual_destination == str(destination_id)
        return {
            "found": True,
            "enabled": bool(exact_topic and exact_destination and status == "ENABLED"),
            "topic_id": actual_topic,
            "destination_id": actual_destination,
            "status": status,
            "topic_matches": exact_topic,
            "destination_matches": exact_destination,
        }
    return {
        "found": False,
        "enabled": False,
        "topic_id": "",
        "destination_id": "",
        "status": "",
        "topic_matches": False,
        "destination_matches": False,
    }


def _subscription_readback_reason(readback: dict[str, Any]) -> str:
    if not readback.get("found"):
        return "shipping_subscription_not_found_after_alignment"
    if not readback.get("topic_matches"):
        return "shipping_subscription_topic_mismatch"
    if not readback.get("destination_matches"):
        return "shipping_subscription_destination_mismatch"
    if str(readback.get("status") or "").upper() != "ENABLED":
        return "shipping_subscription_not_enabled"
    return "shipping_subscription_verification_failed"


def ensure_ebay_shipping_notification_alignment(
    *,
    store: Any,
    access_token: str,
    destination_id: str | None,
) -> dict[str, Any]:
    """Subscribe to ITEM_MARKED_SHIPPED and prove eBay has enabled it."""
    del access_token  # base registration token can remain sell.fulfillment scoped

    if not destination_id:
        return {
            "success": False,
            "ok": False,
            "enabled": False,
            "topic_id": SHIPPING_TOPIC_ID,
            "authorization_required": False,
            "reason": "existing_notification_destination_missing",
            "marketplace_write_started": False,
        }

    token_result = _shipping_access_token(store)
    if not token_result.get("ok"):
        authorization_required = bool(token_result.get("authorization_required"))
        if authorization_required:
            _persist_shipping_consent_state(
                store,
                required=True,
                enabled=False,
                reason=str(token_result.get("reason") or "commerce_shipping_scope_not_granted"),
                destination_id=str(destination_id),
            )
        return {
            "success": True if authorization_required else False,
            "ok": True if authorization_required else False,
            "enabled": False,
            "topic_id": SHIPPING_TOPIC_ID,
            "authorization_required": authorization_required,
            "reauthorization_required": authorization_required,
            "reason": token_result.get("reason"),
            "status_code": token_result.get("status_code"),
            "error": token_result.get("error"),
            "marketplace_write_started": False,
        }

    shipping_token = str(token_result["access_token"])
    probe = _topic_probe(access_token=shipping_token)
    if probe.get("authorization_required"):
        _persist_shipping_consent_state(
            store,
            required=True,
            enabled=False,
            reason="commerce_shipping_scope_not_granted",
            destination_id=str(destination_id),
        )
        return {
            "success": True,
            "ok": True,
            "enabled": False,
            "topic_id": SHIPPING_TOPIC_ID,
            "authorization_required": True,
            "reauthorization_required": True,
            "reason": "commerce_shipping_scope_not_granted",
            "status_code": probe.get("status_code"),
            "marketplace_write_started": False,
        }

    schema_version = str(probe.get("schema_version") or "").strip()
    if not probe.get("ok") or not schema_version:
        return {
            "success": False,
            "ok": False,
            "enabled": False,
            "topic_id": SHIPPING_TOPIC_ID,
            "authorization_required": False,
            "reason": "shipping_topic_schema_unavailable",
            "status_code": probe.get("status_code"),
            "marketplace_write_started": False,
        }

    try:
        subscription_id, created = _ensure_subscription(
            access_token=shipping_token,
            destination_id=str(destination_id),
            topic_id=SHIPPING_TOPIC_ID,
            schema_version=schema_version,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "HTTP 401" in message or "HTTP 403" in message or "Insufficient permissions" in message:
            _persist_shipping_consent_state(
                store,
                required=True,
                enabled=False,
                reason="commerce_shipping_scope_not_granted",
                destination_id=str(destination_id),
            )
            return {
                "success": True,
                "ok": True,
                "enabled": False,
                "topic_id": SHIPPING_TOPIC_ID,
                "authorization_required": True,
                "reauthorization_required": True,
                "reason": "commerce_shipping_scope_not_granted",
                "error": message,
                "marketplace_write_started": False,
            }
        raise

    readback = _shipping_subscription_readback(
        access_token=shipping_token,
        destination_id=str(destination_id),
        subscription_id=str(subscription_id),
    )
    if not readback.get("enabled"):
        reason = _subscription_readback_reason(readback)
        _persist_shipping_consent_state(
            store,
            required=False,
            enabled=False,
            reason=reason,
            subscription_id=str(subscription_id),
            destination_id=str(destination_id),
            subscription_status=str(readback.get("status") or ""),
        )
        return {
            "success": False,
            "ok": False,
            "enabled": False,
            "topic_id": SHIPPING_TOPIC_ID,
            "schema_version": schema_version,
            "subscription_id": subscription_id,
            "subscription_created": created,
            "subscription_verified": False,
            "subscription_status": readback.get("status"),
            "subscription_destination_id": readback.get("destination_id"),
            "authorization_required": False,
            "reauthorization_required": False,
            "reason": reason,
            "marketplace_write_started": False,
        }

    _persist_shipping_consent_state(
        store,
        required=False,
        enabled=True,
        reason=None,
        subscription_id=str(subscription_id),
        destination_id=str(destination_id),
        subscription_status=str(readback.get("status") or "ENABLED"),
        verified=True,
    )
    return {
        "success": True,
        "ok": True,
        "enabled": True,
        "topic_id": SHIPPING_TOPIC_ID,
        "schema_version": schema_version,
        "subscription_id": subscription_id,
        "subscription_created": created,
        "subscription_verified": True,
        "subscription_status": readback.get("status"),
        "subscription_destination_id": readback.get("destination_id"),
        "authorization_required": False,
        "reauthorization_required": False,
        "marketplace_write_started": False,
    }
