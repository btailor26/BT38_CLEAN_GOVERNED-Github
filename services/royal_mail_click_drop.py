"""Royal Mail Click & Drop public API connection and exact-order reads.

This module is intentionally narrow:
- merchant-owned API auth key only
- no Royal Mail website password collection
- no background polling
- no order import loop
- no label purchase path
- exact order/reference reads only

Royal Mail Click & Drop public API base URL:
https://api.parcel.royalmail.com/api/v1
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


BASE_URL = "https://api.parcel.royalmail.com/api/v1"
REQUEST_TIMEOUT_SECONDS = 20


class RoyalMailConfigurationError(RuntimeError):
    pass


class RoyalMailAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _encryption_key() -> bytes:
    raw = str(os.getenv("ROYAL_MAIL_CREDENTIAL_ENCRYPTION_KEY") or "").strip()
    if not raw:
        raise RoyalMailConfigurationError(
            "ROYAL_MAIL_CREDENTIAL_ENCRYPTION_KEY is not configured."
        )
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_api_key(api_key: str) -> str:
    value = str(api_key or "").strip()
    if not value:
        raise ValueError("Royal Mail API auth key is required.")
    nonce = get_random_bytes(12)
    cipher = AES.new(_encryption_key(), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(value.encode("utf-8"))
    return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(str(ciphertext or "").encode("ascii"))
        nonce, tag, payload = raw[:12], raw[12:28], raw[28:]
        cipher = AES.new(_encryption_key(), AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(payload, tag).decode("utf-8")
    except RoyalMailConfigurationError:
        raise
    except Exception as exc:
        raise RoyalMailConfigurationError("Royal Mail API credential could not be decrypted.") from exc


@dataclass
class RoyalMailClickDropClient:
    api_key: str

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": str(self.api_key).strip(),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "BT38-RoyalMail-ClickDrop/1.0",
        }

    def _get(self, path: str) -> requests.Response:
        try:
            return requests.get(
                f"{BASE_URL}{path}",
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise RoyalMailAPIError(f"Royal Mail connection failed: {exc}") from exc

    def validate_connection(self) -> dict[str, Any]:
        """Validate auth without creating, updating or despatching an order.

        A deliberately impossible exact order reference is used. 401 means the
        auth key is invalid. 200 or 404 proves the API accepted authentication.
        """
        probe = '"BT38-CONNECTION-VALIDATION-NO-ORDER"'
        response = self._get(f"/orders/{quote(probe, safe='')}")
        if response.status_code == 401:
            raise RoyalMailAPIError("Royal Mail rejected the API auth key.", status_code=401)
        if response.status_code in {200, 404}:
            return {"success": True, "status_code": response.status_code}
        if response.status_code == 403:
            raise RoyalMailAPIError(
                "Royal Mail accepted authentication but this account is not permitted to use this endpoint.",
                status_code=403,
            )
        if response.status_code >= 400:
            raise RoyalMailAPIError(
                f"Royal Mail validation returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        return {"success": True, "status_code": response.status_code}

    def get_exact_orders(self, order_reference: str) -> list[dict[str, Any]]:
        reference = str(order_reference or "").strip()
        if not reference:
            raise ValueError("Royal Mail order reference is required.")
        encoded = quote(f'"{reference}"', safe="")
        response = self._get(f"/orders/{encoded}")
        if response.status_code == 404:
            return []
        if response.status_code == 401:
            raise RoyalMailAPIError("Royal Mail rejected the API auth key.", status_code=401)
        if response.status_code >= 400:
            raise RoyalMailAPIError(
                f"Royal Mail exact order read returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RoyalMailAPIError("Royal Mail returned a non-JSON order response.") from exc
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []
