"""Google Identity Services verification for the existing BT38 login flow.

This module does not create a second authentication/session system. It only
verifies Google-issued ID tokens so the existing BT38 User + Flask-Login
session remains the authority after identity verification.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any

import requests
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

_JWKS_LOCK = threading.Lock()
_JWKS_BY_KID: dict[str, dict[str, Any]] = {}
_JWKS_EXPIRES_AT = 0.0


class GoogleIdentityError(ValueError):
    """Raised when a Google credential cannot be trusted for BT38 login."""


def _b64url_decode(value: str) -> bytes:
    value = str(value or "").strip()
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise GoogleIdentityError("Invalid Google token encoding") from exc


def _json_segment(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_b64url_decode(value).decode("utf-8"))
    except Exception as exc:
        raise GoogleIdentityError("Invalid Google token JSON") from exc
    if not isinstance(decoded, dict):
        raise GoogleIdentityError("Invalid Google token structure")
    return decoded


def _cache_max_age(cache_control: str | None) -> int:
    for part in str(cache_control or "").split(","):
        key, separator, value = part.strip().partition("=")
        if separator and key.lower() == "max-age":
            try:
                return max(60, min(int(value), 86400))
            except (TypeError, ValueError):
                break
    return 300


def _fetch_google_jwks(*, force: bool = False) -> dict[str, dict[str, Any]]:
    global _JWKS_BY_KID, _JWKS_EXPIRES_AT

    now = time.time()
    with _JWKS_LOCK:
        if not force and _JWKS_BY_KID and now < _JWKS_EXPIRES_AT:
            return dict(_JWKS_BY_KID)

        try:
            response = requests.get(GOOGLE_JWKS_URL, timeout=(3.05, 5.0))
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise GoogleIdentityError("Google signing keys are unavailable") from exc

        keys = {}
        for key in payload.get("keys", []) if isinstance(payload, dict) else []:
            if not isinstance(key, dict):
                continue
            kid = str(key.get("kid") or "").strip()
            if kid:
                keys[kid] = key

        if not keys:
            raise GoogleIdentityError("Google signing keys are unavailable")

        _JWKS_BY_KID = keys
        _JWKS_EXPIRES_AT = now + _cache_max_age(response.headers.get("Cache-Control"))
        return dict(_JWKS_BY_KID)


def _rsa_key_from_jwk(jwk: dict[str, Any]) -> RSA.RsaKey:
    if jwk.get("kty") != "RSA":
        raise GoogleIdentityError("Unsupported Google signing key")
    if jwk.get("alg") not in (None, "RS256"):
        raise GoogleIdentityError("Unsupported Google signing algorithm")

    try:
        modulus = int.from_bytes(_b64url_decode(str(jwk["n"])), "big")
        exponent = int.from_bytes(_b64url_decode(str(jwk["e"])), "big")
        return RSA.construct((modulus, exponent))
    except GoogleIdentityError:
        raise
    except Exception as exc:
        raise GoogleIdentityError("Invalid Google signing key") from exc


def _verify_signature(signing_input: bytes, signature: bytes, jwk: dict[str, Any]) -> None:
    key = _rsa_key_from_jwk(jwk)
    digest = SHA256.new(signing_input)
    try:
        pkcs1_15.new(key).verify(digest, signature)
    except (ValueError, TypeError) as exc:
        raise GoogleIdentityError("Invalid Google token signature") from exc


def _audience_matches(audience: Any, client_id: str) -> bool:
    if isinstance(audience, str):
        return audience == client_id
    if isinstance(audience, list):
        return client_id in audience
    return False


def _authoritative_google_email(claims: dict[str, Any]) -> bool:
    email = str(claims.get("email") or "").strip().lower()
    email_verified = claims.get("email_verified") is True or str(claims.get("email_verified") or "").lower() == "true"
    hosted_domain = str(claims.get("hd") or "").strip().lower()
    return email.endswith("@gmail.com") or (email_verified and bool(hosted_domain))


def verify_google_id_token(token: str, client_id: str, *, now: int | None = None) -> dict[str, Any]:
    """Verify a Google Identity Services ID token and return trusted claims.

    Validation includes RS256 signature, Google issuer, BT38 client audience,
    expiry/not-before timing, stable subject, and an email Google is
    authoritative for. BT38 account activation remains a separate local check.
    """
    token = str(token or "").strip()
    client_id = str(client_id or "").strip()
    if not token or not client_id:
        raise GoogleIdentityError("Google credential is missing")

    parts = token.split(".")
    if len(parts) != 3:
        raise GoogleIdentityError("Invalid Google token structure")

    header = _json_segment(parts[0])
    claims = _json_segment(parts[1])
    signature = _b64url_decode(parts[2])

    if header.get("alg") != "RS256":
        raise GoogleIdentityError("Unsupported Google signing algorithm")

    kid = str(header.get("kid") or "").strip()
    if not kid:
        raise GoogleIdentityError("Google signing key is missing")

    jwks = _fetch_google_jwks()
    jwk = jwks.get(kid)
    if jwk is None:
        # Google rotates signing keys. Refresh once before rejecting a new kid.
        jwk = _fetch_google_jwks(force=True).get(kid)
    if jwk is None:
        raise GoogleIdentityError("Unknown Google signing key")

    _verify_signature(f"{parts[0]}.{parts[1]}".encode("ascii"), signature, jwk)

    current_time = int(time.time()) if now is None else int(now)
    try:
        expires_at = int(claims.get("exp"))
    except (TypeError, ValueError) as exc:
        raise GoogleIdentityError("Google token expiry is missing") from exc
    if expires_at <= current_time:
        raise GoogleIdentityError("Google token has expired")

    if claims.get("nbf") is not None:
        try:
            not_before = int(claims.get("nbf"))
        except (TypeError, ValueError) as exc:
            raise GoogleIdentityError("Invalid Google token timing") from exc
        if not_before > current_time + 60:
            raise GoogleIdentityError("Google token is not valid yet")

    if claims.get("iat") is not None:
        try:
            issued_at = int(claims.get("iat"))
        except (TypeError, ValueError) as exc:
            raise GoogleIdentityError("Invalid Google token timing") from exc
        if issued_at > current_time + 300:
            raise GoogleIdentityError("Google token issue time is invalid")

    if str(claims.get("iss") or "") not in GOOGLE_ISSUERS:
        raise GoogleIdentityError("Invalid Google token issuer")
    if not _audience_matches(claims.get("aud"), client_id):
        raise GoogleIdentityError("Google token was issued for another application")
    if not str(claims.get("sub") or "").strip():
        raise GoogleIdentityError("Google account identifier is missing")

    email = str(claims.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise GoogleIdentityError("Google account email is missing")
    if not _authoritative_google_email(claims):
        raise GoogleIdentityError(
            "Use a Gmail or verified Google Workspace account, or sign in with your BT38 password"
        )

    claims["email"] = email
    return claims
